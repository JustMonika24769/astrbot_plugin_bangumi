from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import aiohttp
import astrbot.api.message_components as Comp
import pytz
from astrbot.api import logger
from astrbot.api.all import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

from .src.app.summary_translation import (
    summary_needs_chinese_translation,
    translate_text_to_chinese,
)
from .src.bangumi_client import BangumiClient, BangumiClientError
from .src.card_renderer import CardRenderError, T2ICardRenderer
from .src.db import BangumiRepository, RepositoryError
from .src.entities import CalendarDay, Subject, SubscriptionView
from .src.plugin_config import PluginConfig
from .src.tracking import SubscriptionManager
from .src.utils.scheduler import SchedulerManager

HELP_COMMANDS = [
    {
        "command": "/bgm <名称|ID> [数量]",
        "description": "搜索全部 Bangumi 条目；ID 会直接查询详情。",
    },
    {"command": "/bgm番剧 <名称|ID>", "description": "仅搜索 TV 动画。"},
    {"command": "/bgm电影 <名称|ID>", "description": "仅搜索动画剧场版。"},
    {"command": "/bgm漫画 <名称|ID>", "description": "仅搜索漫画。"},
    {"command": "/calendar", "description": "查看一周动画放送表。"},
    {"command": "/today", "description": "查看今天的动画放送。"},
    {
        "command": "/追番 <名称|ID>",
        "description": "订阅动画更新；名称有歧义时会给出候选 ID。",
    },
    {
        "command": "/追番列表",
        "description": "查看本会话检测、通知、放送时间和错误状态。",
    },
    {"command": "/追番检查", "description": "立即检查本会话全部订阅，并重试失败通知。"},
    {
        "command": "/追番测试 <名称|ID>",
        "description": "生成当前最新一集测试卡片，不改变通知进度。",
    },
    {"command": "/弃坑 <名称|ID>", "description": "取消本会话订阅。"},
    {
        "command": "/放送时间 [名称|ID] [HH:MM|清空]",
        "description": "查看或修正中国标准时间下的放送时间。",
    },
]


class BangumiPlugin(Star):  # type: ignore[misc]
    """Bangumi 条目检索、放送日历与可靠追番通知。"""

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context, config)
        self.raw_config = config
        self.config = PluginConfig(config)
        self.session: aiohttp.ClientSession | None = None
        self.api: BangumiClient | None = None
        self.repository: BangumiRepository | None = None
        self.cards: T2ICardRenderer | None = None
        self.tracking: SubscriptionManager | None = None
        self.scheduler: SchedulerManager | None = None

    async def initialize(self) -> None:
        data_dir = StarTools.get_data_dir()
        self.session = aiohttp.ClientSession(trust_env=True)
        self.repository = BangumiRepository(os.path.join(data_dir, "data.db"))
        self.api = BangumiClient(
            self.session,
            access_token=self.config.access_token,
            user_agent=self.config.user_agent,
            proxy_url=self.config.proxy_url,
            timeout_seconds=self.config.request_timeout_seconds,
            max_retries=self.config.max_retries,
        )
        self.cards = T2ICardRenderer(
            self.html_render,
            quality=self.config.card_quality,
        )
        self.tracking = SubscriptionManager(
            api=self.api,
            repository=self.repository,
            renderer=self.cards,
            context=self.context,
            config=self.config,
        )

        self.scheduler = SchedulerManager()
        timezone = pytz.timezone("Asia/Shanghai")
        next_check = datetime.now(timezone) + timedelta(seconds=12)
        check_job = self.scheduler.add_job(
            self.tracking.check_updates,
            "interval",
            minutes=self.config.check_interval_minutes,
            next_run_time=next_check,
            id="bangumi-update-check",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        broadcast_job = self.scheduler.add_job(
            self.tracking.refresh_broadcast_times,
            "cron",
            hour=4,
            minute=15,
            id="bangumi-broadcast-refresh",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        if not check_job or not broadcast_job:
            logger.error("Bangumi 定时任务注册不完整，请检查 APScheduler 日志")

        try:
            await self.tracking.refresh_broadcast_times()
        except Exception as exc:
            logger.warning(f"首次刷新放送时间失败，不影响搜索和追番: {exc}")
        logger.info(
            "Bangumi 2.0 初始化完成: "
            f"检查间隔={self.config.check_interval_minutes} 分钟, "
            f"User-Agent={self.config.user_agent}, "
            "卡片渲染=AstrBot T2I"
        )

    async def terminate(self) -> None:
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=False)
        if self.session is not None and not self.session.closed:
            await self.session.close()
        await super().terminate()

    def _session_id(self, event: AstrMessageEvent) -> str | None:
        unified = getattr(event, "unified_msg_origin", None)
        group_id = getattr(getattr(event, "message_obj", None), "group_id", None)
        if isinstance(unified, str) and unified.strip():
            session_id = self._normalize_session_string(unified.strip())
        else:
            raw_session_id = getattr(event, "session_id", None)
            if not raw_session_id:
                return None
            platform_meta = getattr(event, "platform_meta", None)
            platform_id = str(getattr(platform_meta, "id", "aiocqhttp"))
            message_type = "GroupMessage" if group_id else "FriendMessage"
            session_id = f"{platform_id}:{message_type}:{raw_session_id}"

        platform_id = session_id.split(":", 1)[0]
        platform_name = str(
            getattr(getattr(event, "platform_meta", None), "name", "")
        )
        is_legacy_qq_context = (
            platform_id.lower() == "aiocqhttp"
            or platform_name.lower() == "aiocqhttp"
        )
        if group_id and is_legacy_qq_context and self.repository is not None:
            legacy_id = str(group_id)
            aliases = {
                legacy_id,
                f"aiocqhttp:group:{legacy_id}",
                f"aiocqhttp:GroupMessage:{legacy_id}",
            }
            aliases.discard(session_id)
            try:
                migrated = self.repository.migrate_session_aliases(
                    session_id, aliases
                )
                if migrated:
                    logger.info(
                        f"已将 {migrated} 条旧会话订阅迁移到 {session_id}"
                    )
            except RepositoryError as exc:
                logger.warning(f"迁移旧会话订阅失败，继续使用当前会话: {exc}")
        return session_id

    @staticmethod
    def _normalize_session_string(session_id: str) -> str:
        parts = session_id.split(":", 2)
        if len(parts) != 3:
            return session_id
        platform_id, message_type, target = parts
        normalized_type = {
            "group": "GroupMessage",
            "groupmessage": "GroupMessage",
            "friend": "FriendMessage",
            "private": "FriendMessage",
            "friendmessage": "FriendMessage",
            "other": "OtherMessage",
            "othermessage": "OtherMessage",
        }.get(message_type.lower(), message_type)
        return f"{platform_id}:{normalized_type}:{target}"

    def _ready(self) -> bool:
        return all((self.api, self.repository, self.cards, self.tracking))

    async def _translate_subject(self, subject: Subject) -> Subject:
        if (
            not self.config.auto_translate_subject_summary
            or not subject.summary.strip()
            or not summary_needs_chinese_translation(subject.summary)
        ):
            return subject
        translated = await translate_text_to_chinese(
            self.context,
            subject.summary,
            feature_name="条目简介自动翻译",
        )
        if translated == subject.summary:
            return subject
        return replace(subject, summary=translated)

    async def _embed_search_covers(self, subjects: list[Subject]) -> list[Subject]:
        assert self.api is not None
        return list(
            await asyncio.gather(
                *(self.api.with_embedded_cover(subject) for subject in subjects)
            )
        )

    async def _embed_subscription_covers(
        self, subscriptions: list[SubscriptionView]
    ) -> list[SubscriptionView]:
        assert self.api is not None

        async def enrich(item: SubscriptionView) -> SubscriptionView:
            try:
                subject = await self.api.get_subject(int(item.subject_id))
                subject = await self.api.with_embedded_cover(subject)
                return replace(item, cover_url=subject.cover_url)
            except Exception as exc:
                logger.warning(f"订阅 {item.subject_id} 封面预取失败: {exc}")
                return item

        return list(await asyncio.gather(*(enrich(item) for item in subscriptions)))

    async def _render_or_text(
        self,
        event: AstrMessageEvent,
        render_call: Any,
        fallback_text: str,
    ) -> object:
        try:
            path = await render_call
            return event.image_result(path)
        except Exception as exc:
            logger.error(f"卡片渲染失败，回退文字: {type(exc).__name__}: {exc}")
            return event.plain_result(fallback_text)

    async def _help_result(self, event: AstrMessageEvent) -> object:
        assert self.cards is not None
        fallback = "Bangumi 指令\n" + "\n".join(
            f"{item['command']} - {item['description']}" for item in HELP_COMMANDS
        )
        return await self._render_or_text(
            event,
            self.cards.help_card(HELP_COMMANDS),
            fallback,
        )

    async def _search(
        self,
        event: AstrMessageEvent,
        query: str,
        top_k: int,
        *,
        subject_types: tuple[int, ...] | None = None,
        tags: tuple[str, ...] | None = None,
        heading: str = "搜索结果",
    ) -> object:
        assert self.api is not None and self.cards is not None
        normalized = query.strip()
        if not normalized or normalized.lower() in {"help", "帮助", "?"}:
            return await self._help_result(event)

        limit = max(1, min(self.config.search_limit, top_k))
        try:
            subjects = await self.api.search_subjects(
                normalized,
                limit=limit,
                subject_types=subject_types,
                tags=tags,
            )
            if not subjects:
                return event.plain_result(f"没有找到与“{normalized}”匹配的条目")

            if len(subjects) == 1:
                subject = await self.api.get_subject(subjects[0].id)
                subject = await self.api.with_embedded_cover(subject)
                subject = await self._translate_subject(subject)
                latest = None
                if subject.type == 2:
                    latest = await self.api.get_latest_aired_episode(subject.id)
                fallback = self._subject_text(subject, latest.number if latest else 0)
                return await self._render_or_text(
                    event,
                    self.cards.subject_card(subject, latest=latest),
                    fallback,
                )

            subjects = await self._embed_search_covers(subjects)
            fallback = "\n".join(
                f"{index}. {subject.title} (ID:{subject.id})"
                for index, subject in enumerate(subjects, start=1)
            )
            return await self._render_or_text(
                event,
                self.cards.search_card(normalized, subjects, heading=heading),
                fallback,
            )
        except BangumiClientError as exc:
            return event.plain_result(f"Bangumi 查询失败: {exc}")

    @filter.command("bgm")  # type: ignore[untyped-decorator]
    async def search(
        self, event: AstrMessageEvent, query: str = "", top_k: int = 3
    ) -> AsyncGenerator[object, None]:
        if not self._ready():
            yield event.plain_result("Bangumi 服务尚未初始化")
            return
        yield await self._search(event, query, top_k)

    @filter.command(  # type: ignore[untyped-decorator]
        "bgm番剧", alias={"bgm动漫", "bgm动画", "bgm番", "bgm动画片"}
    )
    async def search_anime(
        self, event: AstrMessageEvent, query: str = "", top_k: int = 3
    ) -> AsyncGenerator[object, None]:
        if not self._ready():
            yield event.plain_result("Bangumi 服务尚未初始化")
            return
        yield await self._search(
            event,
            query,
            top_k,
            subject_types=(2,),
            tags=("TV",),
            heading="TV 动画",
        )

    @filter.command("bgm剧场版", alias={"bgm电影"})  # type: ignore[untyped-decorator]
    async def search_movie(
        self, event: AstrMessageEvent, query: str = "", top_k: int = 3
    ) -> AsyncGenerator[object, None]:
        if not self._ready():
            yield event.plain_result("Bangumi 服务尚未初始化")
            return
        yield await self._search(
            event,
            query,
            top_k,
            subject_types=(2,),
            tags=("剧场版",),
            heading="动画剧场版",
        )

    @filter.command("bgm漫画")  # type: ignore[untyped-decorator]
    async def search_manga(
        self, event: AstrMessageEvent, query: str = "", top_k: int = 3
    ) -> AsyncGenerator[object, None]:
        if not self._ready():
            yield event.plain_result("Bangumi 服务尚未初始化")
            return
        yield await self._search(
            event,
            query,
            top_k,
            subject_types=(1,),
            tags=("漫画",),
            heading="漫画",
        )

    @filter.command("calendar", alias={"放送表"})  # type: ignore[untyped-decorator]
    async def calendar(self, event: AstrMessageEvent) -> AsyncGenerator[object, None]:
        if not self._ready():
            yield event.plain_result("Bangumi 服务尚未初始化")
            return
        assert self.api is not None and self.cards is not None
        try:
            days = await self.api.get_calendar()
            yield await self._render_or_text(
                event,
                self.cards.calendar_card(
                    days,
                    heading="每周放送表",
                    subheading="按 Bangumi 星期分组 · 红色为今天",
                ),
                self._calendar_text(days),
            )
        except BangumiClientError as exc:
            yield event.plain_result(f"读取放送表失败: {exc}")

    @filter.command("today", alias={"今日番剧"})  # type: ignore[untyped-decorator]
    async def today(self, event: AstrMessageEvent) -> AsyncGenerator[object, None]:
        if not self._ready():
            yield event.plain_result("Bangumi 服务尚未初始化")
            return
        assert self.api is not None and self.cards is not None
        try:
            days = await self.api.get_calendar()
            today_days = [day for day in days if day.is_today]
            yield await self._render_or_text(
                event,
                self.cards.calendar_card(
                    today_days,
                    heading="今日放送",
                    subheading=datetime.now().strftime("%Y-%m-%d"),
                ),
                self._calendar_text(today_days),
            )
        except BangumiClientError as exc:
            yield event.plain_result(f"读取今日放送失败: {exc}")

    @filter.command("追番")  # type: ignore[untyped-decorator]
    async def subscribe(
        self, event: AstrMessageEvent, query: str = ""
    ) -> AsyncGenerator[object, None]:
        session_id = self._session_id(event)
        if not self._ready() or not session_id:
            yield event.plain_result("订阅服务未就绪或无法识别当前会话")
            return
        normalized = query.strip()
        if not normalized:
            yield event.plain_result("用法：/追番 <动画名称或 Bangumi ID>")
            return
        assert (
            self.api is not None
            and self.cards is not None
            and self.tracking is not None
        )
        try:
            candidates = await self.api.search_subjects(
                normalized,
                limit=self.config.search_limit,
                subject_types=(2,),
            )
            if not candidates:
                yield event.plain_result(f"没有找到动画“{normalized}”")
                return
            if len(candidates) > 1:
                fallback = "匹配到多个条目，请使用 ID 追番：\n" + "\n".join(
                    f"{item.title} (ID:{item.id})" for item in candidates
                )
                result = await self._render_or_text(
                    event,
                    self.cards.search_card(
                        normalized, candidates, heading="请选择准确条目 ID"
                    ),
                    fallback,
                )
                yield result
                return

            subject = await self.api.get_subject(candidates[0].id)
            outcome = await self.tracking.subscribe(session_id, subject)
            subject_for_card = await self.api.with_embedded_cover(subject)
            subject_for_card = await self._translate_subject(subject_for_card)
            status = "订阅成功" if outcome.created else "本会话已经订阅过该条目"
            try:
                path = await self.cards.subject_card(
                    subject_for_card,
                    latest=outcome.latest_episode,
                    subscribed=True,
                )
            except CardRenderError as exc:
                logger.error(f"订阅已保存，但确认卡片渲染失败: {exc}")
                latest_number = (
                    outcome.latest_episode.number if outcome.latest_episode else 0
                )
                yield event.plain_result(
                    f"{status}：《{subject.title}》\n"
                    f"当前通知基线：EP {latest_number}\n"
                    "确认卡片渲染失败，请使用 /追番测试 检查 AstrBot T2I。"
                )
                return
            yield event.chain_result(
                [
                    Comp.Image.fromFileSystem(path),
                    Comp.Plain(f"\n{status}：{subject_for_card.title}"),
                ]
            )
        except (BangumiClientError, RepositoryError) as exc:
            yield event.plain_result(f"追番失败: {exc}")

    @filter.command("弃坑")  # type: ignore[untyped-decorator]
    async def unsubscribe(
        self, event: AstrMessageEvent, query: str = ""
    ) -> AsyncGenerator[object, None]:
        session_id = self._session_id(event)
        if not self._ready() or not session_id:
            yield event.plain_result("订阅服务未就绪或无法识别当前会话")
            return
        if not query.strip():
            yield event.plain_result("用法：/弃坑 <动画名称或 Bangumi ID>")
            return
        assert self.repository is not None
        matches = self.repository.find_subscription(session_id, query)
        if not matches:
            yield event.plain_result(f"本会话没有与“{query}”匹配的订阅")
            return
        if len(matches) > 1:
            yield event.plain_result(
                "匹配到多个订阅，请使用 ID：\n"
                + "\n".join(
                    f"{item.title} (ID:{item.subject_id})" for item in matches[:5]
                )
            )
            return
        item = matches[0]
        if self.repository.unsubscribe(session_id, item.subject_id):
            yield event.plain_result(f"已取消订阅《{item.title}》")
        else:
            yield event.plain_result("取消订阅失败，订阅关系可能已不存在")

    @filter.command("追番列表", alias={"追番状态"})  # type: ignore[untyped-decorator]
    async def subscription_list(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[object, None]:
        session_id = self._session_id(event)
        if not self._ready() or not session_id:
            yield event.plain_result("订阅服务未就绪或无法识别当前会话")
            return
        assert self.repository is not None and self.cards is not None
        subscriptions = self.repository.list_subscriptions(session_id)
        if not subscriptions:
            yield event.plain_result("本会话还没有追番订阅")
            return
        subscriptions_for_card = await self._embed_subscription_covers(subscriptions)
        yield await self._render_or_text(
            event,
            self.cards.subscriptions_card(subscriptions_for_card),
            self._subscriptions_text(subscriptions),
        )

    @filter.command("追番检查")  # type: ignore[untyped-decorator]
    async def check_subscriptions(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[object, None]:
        session_id = self._session_id(event)
        if not self._ready() or not session_id:
            yield event.plain_result("订阅服务未就绪或无法识别当前会话")
            return
        assert self.tracking is not None and self.cards is not None
        report = await self.tracking.check_updates(session_id=session_id, refresh=True)
        yield await self._render_or_text(
            event,
            self.cards.report_card(report),
            report.summary
            + ("\n" + "\n".join(report.details) if report.details else ""),
        )

    @filter.command("追番测试")  # type: ignore[untyped-decorator]
    async def test_subscription_card(
        self, event: AstrMessageEvent, query: str = ""
    ) -> AsyncGenerator[object, None]:
        session_id = self._session_id(event)
        if not self._ready() or not session_id:
            yield event.plain_result("订阅服务未就绪或无法识别当前会话")
            return
        if not query.strip():
            yield event.plain_result("用法：/追番测试 <动画名称或 Bangumi ID>")
            return
        assert self.tracking is not None
        try:
            path = await self.tracking.render_test_card(session_id, query)
            yield event.image_result(path)
        except Exception as exc:
            yield event.plain_result(f"测试卡片生成失败: {exc}")

    @filter.command("放送时间")  # type: ignore[untyped-decorator]
    async def broadcast_time(
        self,
        event: AstrMessageEvent,
        query: str = "",
        value: str = "",
    ) -> AsyncGenerator[object, None]:
        session_id = self._session_id(event)
        if not self._ready() or not session_id:
            yield event.plain_result("订阅服务未就绪或无法识别当前会话")
            return
        assert self.repository is not None and self.cards is not None
        if not query.strip():
            subscriptions = self.repository.list_subscriptions(session_id)
            if not subscriptions:
                yield event.plain_result("本会话还没有追番订阅")
                return
            subscriptions_for_card = await self._embed_subscription_covers(
                subscriptions
            )
            yield await self._render_or_text(
                event,
                self.cards.subscriptions_card(subscriptions_for_card),
                self._subscriptions_text(subscriptions),
            )
            return

        matches = self.repository.find_subscription(session_id, query)
        if not matches:
            yield event.plain_result(f"本会话没有与“{query}”匹配的订阅")
            return
        if len(matches) > 1:
            yield event.plain_result("匹配到多个订阅，请改用准确 ID")
            return
        item = matches[0]
        normalized_value = value.strip()
        if not normalized_value:
            yield event.plain_result(
                f"《{item.title}》当前放送时间：{item.broadcast_time or '未设置'}（CST）"
            )
            return
        if normalized_value in {"清空", "清除", "reset", "none"}:
            target_time = None
        elif re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", normalized_value):
            target_time = normalized_value
        else:
            yield event.plain_result(
                "时间格式错误，请使用 HH:MM，例如 22:30，或使用“清空”"
            )
            return
        self.repository.set_broadcast_time(item.subject_id, target_time)
        yield event.plain_result(
            f"已将《{item.title}》放送时间设置为 {target_time or '未设置'}（CST）"
        )

    @filter.command("bgm模板")  # type: ignore[untyped-decorator]
    async def legacy_template_command(
        self, event: AstrMessageEvent, _value: str = ""
    ) -> AsyncGenerator[object, None]:
        yield event.plain_result(
            "2.0 已统一使用 AstrBot T2I 卡片，不再需要选择渲染模板。"
        )

    @staticmethod
    def _subject_text(subject: Subject, latest_episode: int) -> str:
        lines = [f"{subject.title} (ID:{subject.id})"]
        if subject.original_title:
            lines.append(subject.original_title)
        lines.append(
            f"评分 {subject.score:.1f} | 排名 {subject.rank or '--'} | "
            f"已播 EP{latest_episode} / {subject.total_episodes or '?'}"
        )
        if subject.summary:
            lines.append(subject.summary[:300])
        lines.append(subject.url)
        return "\n".join(lines)

    @staticmethod
    def _calendar_text(days: list[CalendarDay]) -> str:
        if not days:
            return "暂无放送数据"
        return "\n".join(
            [
                day.weekday_name
                + "："
                + ("、".join(item.title for item in day.items) or "暂无")
                for day in days
            ]
        )

    @staticmethod
    def _subscriptions_text(subscriptions: list[SubscriptionView]) -> str:
        return "\n".join(
            f"{item.title} (ID:{item.subject_id}) "
            f"API EP{item.current_episode} / 已通知 EP{item.last_notified_episode} "
            f"放送 {item.broadcast_time or '未设置'}"
            for item in subscriptions
        )
