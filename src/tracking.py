from __future__ import annotations

import asyncio
from dataclasses import replace

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.star import Context

from .api.bgmlist import fetch_onair_data
from .app.summary_translation import (
    summary_needs_chinese_translation,
    translate_text_to_chinese,
)
from .bangumi_client import BangumiClient
from .card_renderer import CardRenderError, T2ICardRenderer
from .db import BangumiRepository
from .entities import (
    BroadcastSchedule,
    Episode,
    Subject,
    SubscribeResult,
    UpdateReport,
)
from .plugin_config import PluginConfig


class SubscriptionManager:
    def __init__(
        self,
        *,
        api: BangumiClient,
        repository: BangumiRepository,
        renderer: T2ICardRenderer,
        context: Context,
        config: PluginConfig,
    ) -> None:
        self.api = api
        self.repository = repository
        self.renderer = renderer
        self.context = context
        self.config = config
        self._check_lock = asyncio.Lock()
        self._broadcast_schedules: dict[str, BroadcastSchedule] = {}

    async def refresh_broadcast_times(self) -> int:
        mapping = await fetch_onair_data(
            session=self.api.session,
            proxy_url=self.config.proxy_url,
        )
        if not mapping:
            logger.warning("bgmlist 放送时间不可用，保留现有设置")
            return 0
        self._broadcast_schedules = mapping
        updated = self.repository.apply_broadcast_schedules(mapping)
        logger.info(f"放送时间刷新完成: API={len(mapping)}, 数据库更新={updated}")
        return updated

    async def subscribe(self, session_id: str, subject: Subject) -> SubscribeResult:
        schedule = self._broadcast_schedules.get(str(subject.id))
        broadcast_time = schedule.broadcast_time if schedule else None
        latest = await self.api.get_latest_aired_episode(
            subject.id, broadcast_time=broadcast_time, refresh=True
        )
        baseline = latest.number if latest else 0
        created = self.repository.subscribe(
            session_id,
            subject,
            baseline_episode=baseline,
            broadcast_date=schedule.broadcast_date if schedule else None,
            broadcast_time=broadcast_time,
        )
        return SubscribeResult(subject=subject, latest_episode=latest, created=created)

    async def check_updates(
        self,
        *,
        session_id: str | None = None,
        refresh: bool = True,
    ) -> UpdateReport:
        if self._check_lock.locked():
            return UpdateReport(skipped=True)

        async with self._check_lock:
            tracked = self.repository.list_tracked_subjects(session_id=session_id)
            report = UpdateReport(subjects_total=len(tracked))
            logger.info(
                f"开始追番检查: 条目={len(tracked)}, 范围={session_id or '全部会话'}"
            )
            for item in tracked:
                report.subjects_checked += 1
                try:
                    subject = await self.api.get_subject(
                        int(item.subject_id), refresh=refresh
                    )
                    latest = await self.api.get_latest_aired_episode(
                        int(item.subject_id),
                        broadcast_time=item.broadcast_time,
                        refresh=refresh,
                    )
                    if latest is None:
                        report.no_episode += 1
                        self.repository.upsert_subject(subject)
                        self.repository.mark_checked(item.subject_id)
                        detail = f"《{subject.title}》暂无符合播出条件的普通剧集"
                        report.details.append(detail)
                        logger.info(detail)
                        continue

                    self.repository.upsert_subject(
                        subject, current_episode=latest.number
                    )
                    self.repository.mark_checked(
                        item.subject_id, current_episode=latest.number
                    )
                    pending_sessions = self.repository.pending_sessions(
                        item.subject_id, latest.number
                    )
                    pending_sessions = self._canonicalize_pending_sessions(
                        item.subject_id,
                        latest.number,
                        pending_sessions,
                    )
                    if session_id is not None:
                        pending_sessions = [
                            session
                            for session in pending_sessions
                            if session == session_id
                        ]
                    detail = (
                        f"《{subject.title}》API EP{latest.number}，"
                        f"待通知 {len(pending_sessions)} 个会话"
                    )
                    report.details.append(detail)
                    logger.info(detail)
                    if not pending_sessions:
                        continue

                    report.pending_deliveries += len(pending_sessions)
                    episode = await self._translate_episode(latest)
                    subject_for_card = await self.api.with_embedded_cover(subject)
                    progress = self.repository.delivery_progress(
                        item.subject_id, pending_sessions
                    )
                    image_paths: dict[int, str | None] = {}
                    for previous_episode in sorted(set(progress.values())):
                        try:
                            image_paths[previous_episode] = (
                                await self.renderer.update_card(
                                    subject_for_card,
                                    episode,
                                    previous_episode=previous_episode,
                                )
                            )
                        except CardRenderError as exc:
                            image_paths[previous_episode] = None
                            logger.error(
                                f"{exc}（通知基线 EP{previous_episode}）"
                            )

                    for target_session in pending_sessions:
                        try:
                            previous_episode = progress.get(target_session, 0)
                            await self._send_update(
                                target_session,
                                subject,
                                episode,
                                image_path=image_paths.get(previous_episode),
                            )
                            self.repository.mark_notified(
                                target_session, item.subject_id, episode.number
                            )
                            report.delivered += 1
                        except Exception as exc:
                            report.failed += 1
                            message = f"{type(exc).__name__}: {exc}"
                            self.repository.mark_delivery_error(
                                target_session, item.subject_id, message
                            )
                            logger.error(
                                f"通知《{subject.title}》到 {target_session} 失败，"
                                f"下轮重试: {message}"
                            )
                except Exception as exc:
                    report.failed += 1
                    message = f"{type(exc).__name__}: {exc}"
                    try:
                        self.repository.mark_checked(item.subject_id, error=message)
                    except Exception as state_exc:
                        logger.error(f"记录《{item.title}》检查错误失败: {state_exc}")
                    report.details.append(f"《{item.title}》检查失败: {message}")
                    logger.error(f"检查《{item.title}》失败: {message}")

            logger.info(f"追番检查完成: {report.summary}")
            return report

    def _canonicalize_pending_sessions(
        self,
        subject_id: str,
        episode_number: int,
        pending_sessions: list[str],
    ) -> list[str]:
        aliases_by_target: dict[str, set[str]] = {}
        for source_session in pending_sessions:
            try:
                target_session = self._notification_session(source_session)
            except RuntimeError:
                continue
            if target_session != source_session:
                aliases_by_target.setdefault(target_session, set()).add(
                    source_session
                )

        migrated = 0
        for target_session, aliases in aliases_by_target.items():
            migrated += self.repository.migrate_session_aliases(
                target_session, aliases
            )
        if not migrated:
            return pending_sessions

        normalized = self.repository.pending_sessions(
            subject_id, episode_number
        )
        logger.info(
            f"会话别名合并: 条目={subject_id}, "
            f"原始待通知={len(pending_sessions)}, "
            f"合并后={len(normalized)}, 迁移订阅={migrated}"
        )
        return normalized

    async def render_test_card(self, session_id: str, query: str) -> str:
        matches = self.repository.find_subscription(session_id, query)
        if not matches:
            raise ValueError(f"本会话没有与“{query}”匹配的订阅")
        if len(matches) > 1:
            names = "、".join(
                f"{item.title}(ID:{item.subject_id})" for item in matches[:5]
            )
            raise ValueError(f"匹配到多个订阅，请使用 ID：{names}")
        item = matches[0]
        subject = await self.api.get_subject(int(item.subject_id), refresh=True)
        latest = await self.api.get_latest_aired_episode(
            int(item.subject_id),
            broadcast_time=item.broadcast_time,
            refresh=True,
        )
        if latest is None:
            raise ValueError("当前没有符合播出条件的剧集可用于测试")
        latest = await self._translate_episode(latest)
        subject = await self.api.with_embedded_cover(subject)
        return await self.renderer.update_card(
            subject,
            latest,
            previous_episode=item.last_notified_episode,
        )

    async def _translate_episode(self, episode: Episode) -> Episode:
        if (
            not self.config.auto_translate_episode_summary
            or not episode.summary.strip()
            or not summary_needs_chinese_translation(episode.summary)
        ):
            return episode
        translated = await translate_text_to_chinese(
            self.context,
            episode.summary,
            feature_name="单集简介自动翻译",
        )
        if translated == episode.summary:
            return episode
        return replace(episode, summary=translated)

    async def _send_update(
        self,
        session_id: str,
        subject: Subject,
        episode: Episode,
        *,
        image_path: str | None,
    ) -> None:
        if image_path:
            chain = MessageChain([Comp.Image.fromFileSystem(image_path)])
        else:
            chain = MessageChain(
                [
                    Comp.Plain(
                        f"番剧《{subject.title}》更新至第 {episode.number} 集\n"
                        f"{episode.title}\n{episode.url}"
                    )
                ]
            )
        session = self._notification_session(session_id)
        if not await self.context.send_message(session, chain):
            raise RuntimeError(f"找不到主动发送平台: {session}")

    def _notification_session(self, session_id: str) -> str:
        parts = session_id.split(":", 2)
        if len(parts) == 3:
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
            candidates = self._platform_ids(adapter_name=platform_id)
            if platform_id in candidates:
                return f"{platform_id}:{normalized_type}:{target}"
            if len(candidates) == 1:
                return f"{candidates[0]}:{normalized_type}:{target}"
            if len(candidates) > 1:
                raise RuntimeError(
                    f"存在多个 {platform_id} 平台实例，无法确定旧会话 {session_id} "
                    "应发送到哪个实例；请在目标群执行 /追番列表 完成迁移"
                )
            return f"{platform_id}:{normalized_type}:{target}"

        candidates = self._platform_ids(adapter_name="aiocqhttp")
        if len(candidates) == 1:
            return f"{candidates[0]}:GroupMessage:{session_id}"
        if not candidates:
            raise RuntimeError(
                f"未找到 aiocqhttp 平台实例，无法发送旧 QQ 群会话 {session_id}"
            )
        raise RuntimeError(
            f"存在多个 aiocqhttp 平台实例，无法确定旧 QQ 群会话 {session_id} "
            "应发送到哪个实例；请在目标群执行 /追番列表 完成迁移"
        )

    def _platform_ids(self, *, adapter_name: str) -> list[str]:
        manager = getattr(self.context, "platform_manager", None)
        platforms = getattr(manager, "platform_insts", ())
        result: list[str] = []
        for platform in platforms:
            try:
                metadata = platform.meta()
            except Exception as exc:
                logger.warning(f"读取 AstrBot 平台元数据失败: {exc}")
                continue
            platform_id = str(getattr(metadata, "id", "")).strip()
            platform_name = str(getattr(metadata, "name", "")).strip()
            if platform_id and (
                platform_name.lower() == adapter_name.lower()
                or platform_id == adapter_name
            ):
                result.append(platform_id)
        return result
