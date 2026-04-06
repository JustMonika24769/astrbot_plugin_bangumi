import copy
import os
import re
from collections.abc import AsyncGenerator

import aiohttp
import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.all import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageChain, filter

# 导入配置与管理
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.utils.session_waiter import (
    SessionController,
    SessionFilter,
    session_waiter,
)

from .src.config import ConfigManager
from .src.db import BangumiRepository

# 导入逻辑服务
from .src.services import BangumiService, SearchService, SubscriptionService
from .src.utils import EnvManager, SchedulerManager


@register(
    "astrbot_plugin_bangumi_enhance",
    "united_pooh",
    "AstrBot Bangumi 增强版:为 AstrBot 打造的一站式 Bangumi 追番助手支持番剧/漫画图文搜索、每日放送时刻表查看及集数更新自动提醒",
    "v1.1.2",
    "https://github.com/united-pooh/astrbot_plugin_bangumi",
)
class BangumiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        """
        初始化 BangumiPlugin 插件
        """
        super().__init__(context)
        self.config = config
        self.config_manager = ConfigManager(config)
        self.scheduler_manager = SchedulerManager()

        self.session: aiohttp.ClientSession | None = None
        self.storage: BangumiRepository | None = None
        self.service: BangumiService | None = None
        self.subscription_service: SubscriptionService | None = None
        self.search_service: SearchService | None = None
        self.env_manager: EnvManager | None = None

    async def initialize(self) -> None:
        """
        插件加载时自动运行的初始化方法
        """
        # 0. 提前获取插件数据目录(必须先于所有依赖 StarTools 的操作)
        plugin_data_dir = StarTools.get_data_dir()

        # 1. 初始化数据库
        try:
            db_path = os.path.join(plugin_data_dir, "data.db")
            self.storage = BangumiRepository(db_path=db_path)
        except (OSError, RuntimeError, ValueError, TypeError) as e:
            logger.error(f"数据库初始化失败: {e}")

        # 2. 初始化网络会话 (Shared Session)
        self.session = aiohttp.ClientSession()

        # 3. 初始化核心 API 服务
        try:
            proxy_url = None
            proxy_host = self.config_manager.get_proxy_http()
            proxy_port = self.config_manager.get_port()
            if proxy_host and proxy_port:
                proxy_url = f"{proxy_host}:{proxy_port}"

            self.service = BangumiService(
                access_token=self.config_manager.get_access_token(),
                user_agent=self.config_manager.get_user_agent(),
                proxy=proxy_url,
                session=self.session,
            )
        except (RuntimeError, ValueError, TypeError) as e:
            logger.error(f"服务初始化失败: {e}")

        # 4. 初始化业务逻辑服务 (Dependency Injection)
        if self.service:
            # 搜索服务
            self.search_service = SearchService(
                service=self.service,
                config_manager=self.config_manager,
                session=self.session,
            )

            # 订阅服务
            if self.storage:
                self.subscription_service = SubscriptionService(
                    repository=self.storage,
                    service=self.service,
                    config_manager=self.config_manager,
                    session=self.session,
                )

        # 5. 其他初始化流程
        self.env_manager = EnvManager(plugin_data_dir)

        # 检查本地渲染环境
        if not self.env_manager.is_installed():
            logger.info("本地 Playwright 环境未就绪,将优先使用 RPC 渲染(如果已配置)")

        # 添加定时更新任务
        if self.subscription_service:
            try:
                self.scheduler_manager.add_job(
                    func=self.subscription_service.check_updates,
                    trigger="cron",
                    minute=0,
                )
                logger.info("Bangumi 插件定时更新任务已启动")
            except (RuntimeError, ValueError, TypeError) as e:
                logger.error(f"添加定时任务失败: {e}")

        logger.info("Bangumi 插件初始化流程结束")

    # --- 命令处理区 ---

    @staticmethod
    def _resolve_session_key(event: AstrMessageEvent) -> str | None:
        session_key: str | None = getattr(event, "session_id", None)
        if hasattr(event, "message_obj") and hasattr(event.message_obj, "group_id"):
            session_key = event.message_obj.group_id
        return session_key

    @staticmethod
    def _parse_subscribe_selection(raw_text: str) -> int | None:
        match = re.match(r"^/?追番\s+(\d+)\s*$", raw_text.strip())
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _normalize_command_token(raw_text: str) -> str:
        stripped = raw_text.strip()
        if not stripped:
            return ""
        first_token = stripped.split(maxsplit=1)[0]
        return first_token[1:] if first_token.startswith("/") else first_token

    @classmethod
    def _should_requeue_subscribe_command(cls, raw_text: str) -> bool:
        stripped = raw_text.strip()
        if not stripped:
            return False
        if cls._parse_subscribe_selection(stripped) is not None:
            return False

        normalized_token = cls._normalize_command_token(stripped)
        return bool(normalized_token) and (
            stripped.startswith("/") or normalized_token == "追番"
        )

    @filter.command("bgm")
    async def search(
        self, event: AstrMessageEvent, query: str, top_k: int = 1
    ) -> AsyncGenerator[object, None]:
        """全类别搜索 Bangumi 条目。"""
        if not self.search_service:
            yield event.plain_result("❌ 搜索服务未就绪")
            return
        async for result in self.search_service.handle_subject_search(
            event, query, top_k, subject_type=None
        ):
            yield result

    @filter.command("bgm番剧")
    async def search_anime(
        self, event: AstrMessageEvent, query: str, top_k: int = 1
    ) -> AsyncGenerator[object, None]:
        """仅搜索 TV 动画条目。"""
        if not self.search_service:
            yield event.plain_result("❌ 搜索服务未就绪")
            return
        async for result in self.search_service.handle_subject_search(
            event, query, top_k, subject_type=[2], subject_tags=["TV"]
        ):
            yield result

    @filter.command("bgm剧场版")
    async def search_movie(
        self, event: AstrMessageEvent, query: str, top_k: int = 1
    ) -> AsyncGenerator[object, None]:
        """仅搜索剧场版动画条目。"""
        if not self.search_service:
            yield event.plain_result("❌ 搜索服务未就绪")
            return
        async for result in self.search_service.handle_subject_search(
            event, query, top_k, subject_type=[2], subject_tags=["剧场版"]
        ):
            yield result

    @filter.command("bgm漫画")
    async def search_manga(
        self, event: AstrMessageEvent, query: str, top_k: int = 1
    ) -> AsyncGenerator[object, None]:
        """仅搜索漫画条目。"""
        if not self.search_service:
            yield event.plain_result("❌ 搜索服务未就绪")
            return
        async for result in self.search_service.handle_subject_search(
            event, query, top_k, subject_type=[1], subject_tags=["漫画"]
        ):
            yield result

    @filter.command("calendar")
    async def calendar(self, event: AstrMessageEvent) -> AsyncGenerator[object, None]:
        """获取今日番剧放送表。"""
        if not self.search_service:
            yield event.plain_result("❌ 搜索服务未就绪")
            return
        async for result in self.search_service.handle_calendar(event):
            yield result

    @filter.command("today")
    async def today(self, event: AstrMessageEvent) -> AsyncGenerator[object, None]:
        if not self.search_service:
            yield event.plain_result("❌ 搜索服务未就绪")
            return
        async for result in self.search_service.handle_today(event):
            yield result

    @filter.command("追番")
    async def subscribe(
        self, event: AstrMessageEvent, query: str
    ) -> AsyncGenerator[object, None]:
        """订阅番剧，更新时自动通知。"""
        if not self.subscription_service:
            yield event.plain_result("❌ 订阅服务未就绪")
            return

        group_id = self._resolve_session_key(event)
        if not group_id:
            yield event.plain_result("❌ 无法获取群组ID")
            return

        (
            error_msg,
            candidates,
        ) = await self.subscription_service.get_subscribe_candidates(
            keyword=query,
            limit=self.config_manager.get_max_fuzzy_results(),
        )
        if error_msg:
            yield event.plain_result(error_msg)
            return
        if not candidates:
            yield event.plain_result("🔍 未找到相关番剧")
            return

        if len(candidates) == 1:
            result = await self.subscription_service.subscribe_by_subject_id(
                group_id=group_id,
                subject_id=candidates[0]["subject_id"],
            )
            yield event.plain_result(result)
            return

        candidate_lines = ["⚠️ 匹配到多个候选,请使用 `/追番 序号` 确认:"]
        for index, candidate in enumerate(candidates, start=1):
            candidate_lines.append(
                f"{index}. {candidate['name']} (ID: {candidate['subject_id']})"
            )
        candidate_lines.append("5分钟内有效;若发送新的斜杠命令或重新输入 `追番` 将自动取消本次确认")
        yield event.plain_result("\n".join(candidate_lines))
        session_key = group_id

        class GroupSessionFilter(SessionFilter):
            def filter(self, wait_event: AstrMessageEvent) -> str:
                wait_session_key = BangumiPlugin._resolve_session_key(wait_event)
                return wait_session_key or wait_event.unified_msg_origin

        @session_waiter(timeout=300)
        async def subscribe_confirm_waiter(
            controller: SessionController,
            wait_event: AstrMessageEvent,
        ) -> None:
            incoming_text = wait_event.get_message_str().strip()
            if self._should_requeue_subscribe_command(incoming_text):
                new_event = copy.copy(wait_event)
                self.context.get_event_queue().put_nowait(new_event)
                wait_event.stop_event()
                controller.stop()
                return

            selected_index = self._parse_subscribe_selection(incoming_text)
            if selected_index is None:
                controller.keep(timeout=0)
                return
            if selected_index < 1 or selected_index > len(candidates):
                await wait_event.send(
                    MessageChain(
                        [Comp.Plain(f"❌ 序号超出范围,请输入 1-{len(candidates)}")]
                    )
                )
                controller.keep(timeout=0)
                return

            selected = candidates[selected_index - 1]
            result = await self.subscription_service.subscribe_by_subject_id(
                group_id=session_key,
                subject_id=selected["subject_id"],
            )
            await wait_event.send(MessageChain([Comp.Plain(result)]))
            wait_event.stop_event()
            controller.stop()

        try:
            await subscribe_confirm_waiter(
                event,
                session_filter=GroupSessionFilter(),
            )
        except TimeoutError:
            yield event.plain_result("⏰ 候选确认已过期,请重新使用 `/追番 关键词`")

    @filter.command("弃坑")
    async def unsubscribe(
        self, event: AstrMessageEvent, query: str
    ) -> AsyncGenerator[object, None]:
        """取消订阅番剧。"""
        if not self.subscription_service:
            yield event.plain_result("❌ 订阅服务未就绪")
            return

        group_id = self._resolve_session_key(event)
        if not group_id:
            yield event.plain_result("❌ 无法获取群组ID")
            return

        result = await self.subscription_service.unsubscribe(group_id, query)
        yield event.plain_result(result)

    async def terminate(self) -> None:
        logger.info("正在清理 Bangumi 插件资源...")
        if self.scheduler_manager.scheduler.running:
            self.scheduler_manager.scheduler.shutdown(wait=False)

        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("已关闭共享网络会话")

        await super().terminate()
