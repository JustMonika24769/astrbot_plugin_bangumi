from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from astrbot.api import logger
from astrbot.api.star import Context

from .airing import episode_schedule, weekly_schedule
from .bangumi_client import BangumiClient, BangumiClientError
from .db import BangumiRepository, RepositoryError
from .entities import Subject
from .tracking import SubscriptionManager

PLUGIN_NAME = "astrbot_plugin_bangumi_enhance"
CST = timezone(timedelta(hours=8))


async def request_body() -> dict[str, Any]:
    # api.web is the public API in newer AstrBot; older supported releases use Quart.
    try:
        from astrbot.api.web import request
    except ImportError:
        from quart import request as quart_request

        payload = await quart_request.get_json(silent=True)
    else:
        payload = await request.json(default=None)
    if not isinstance(payload, dict):
        raise ValueError("请提交有效的 JSON 对象")
    return payload


class BangumiWebUI:
    """Dashboard-authenticated API, sharing the plugin's repository and tracker."""

    def __init__(
        self,
        context: Context,
        api: BangumiClient,
        repository: BangumiRepository,
        tracking: SubscriptionManager,
    ) -> None:
        self.context = context
        self.api = api
        self.repository = repository
        self.tracking = tracking
        self.jobs: list[dict[str, Any]] = []
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self._routes: list[tuple[str, Any]] = []

    def register(self) -> None:
        handlers: dict[str, tuple[str, Callable[[], Awaitable[dict[str, Any]]]]] = {
            "state": ("GET", self.state),
            "search": ("POST", self.search),
            "subscribe": ("POST", self.subscribe),
            "unsubscribe": ("POST", self.unsubscribe),
            "check": ("POST", self.check),
            "calendar": ("GET", self.calendar),
            "cover": ("POST", self.cover),
            "subject": ("POST", self.subject),
        }
        for action, (method, handler) in handlers.items():
            route = f"/{PLUGIN_NAME}/webui/{action}"
            wrapped = self._guard(handler)
            self.context.register_web_api(
                route, wrapped, [method], f"追番手帐 · {action}"
            )
            self._routes.append((route, wrapped))

    def _guard(
        self, handler: Callable[[], Awaitable[dict[str, Any]]]
    ) -> Callable[[], Awaitable[dict[str, Any]]]:
        async def guarded() -> dict[str, Any]:
            if self._closed:
                return {"status": "error", "message": "插件已卸载，请刷新页面"}
            try:
                return {"status": "ok", "data": await handler()}
            except (ValueError, BangumiClientError, RepositoryError) as exc:
                return {"status": "error", "message": str(exc)}
            except Exception:
                logger.exception("追番手帐请求失败")
                return {
                    "status": "error",
                    "message": "操作未完成，请查看 AstrBot 日志后重试",
                }

        return guarded

    async def close(self) -> None:
        self._closed = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        registered = getattr(self.context, "registered_web_apis", None)
        if isinstance(registered, list):
            owned_handlers = {id(handler) for _, handler in self._routes}
            registered[:] = [
                entry for entry in registered if id(entry[1]) not in owned_handlers
            ]
        self._routes.clear()

    def platforms(self) -> list[dict[str, str]]:
        result = []
        for platform in getattr(
            getattr(self.context, "platform_manager", None), "platform_insts", ()
        ):
            meta = platform.meta()
            if meta.id:
                result.append({"id": str(meta.id), "name": str(meta.name)})
        return result

    async def state(self) -> dict[str, Any]:
        rows = self.repository.list_subscriptions()
        subscriptions = []
        for row in rows:
            data = asdict(row)
            data.update(
                pending=row.is_pending,
                broadcast_schedule=row.broadcast_schedule,
                weekly_schedule=weekly_schedule(row.broadcast_date, row.broadcast_time),
            )
            subscriptions.append(data)
        return {
            "subscriptions": subscriptions,
            "platforms": self.platforms(),
            "jobs": self.jobs,
            "checking": bool(self._task and not self._task.done())
            or self.tracking._check_lock.locked(),
            "checked_at": datetime.now(CST).isoformat(timespec="seconds"),
        }

    @staticmethod
    def _text(body: dict[str, Any], key: str, *, maximum: int = 300) -> str:
        value = body.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ValueError(f"{key} 不能为空，且不能超过 {maximum} 个字符")
        return value.strip()

    @classmethod
    def _subject_id(cls, body: dict[str, Any]) -> int:
        raw = cls._text(body, "subject_id", maximum=12)
        if not re.fullmatch(r"[0-9]+", raw) or int(raw) <= 0:
            raise ValueError("请输入有效的 Bangumi 条目 ID")
        return int(raw)

    async def search(self) -> dict[str, Any]:
        body = await request_body()
        query = self._text(body, "query", maximum=100)
        subjects = await self.api.search_subjects(query, limit=10, subject_types=(2,))
        return {
            "subjects": [
                asdict(subject) | {"title": subject.title, "url": subject.url}
                for subject in subjects
            ]
        }

    async def subject(self) -> dict[str, Any]:
        body = await request_body()
        subject_id = self._subject_id(body)
        subject = await self.api.get_subject(subject_id)
        stored = self.repository.broadcast_schedule(str(subject_id))
        result: dict[str, Any] = {
            "subject": asdict(subject) | {"title": subject.title, "url": subject.url},
            "weekly_schedule": weekly_schedule(
                stored.broadcast_date if stored else None,
                stored.broadcast_time if stored else None,
            ),
        }
        try:
            episodes = await self.api.get_episodes(subject_id)
        except BangumiClientError:
            result.update(
                episodes=[], airing={"message": "单集排期暂时无法读取，请稍后重试。"}
            )
        else:
            result.update(
                episodes=[
                    asdict(ep) | {"title": ep.title} for ep in episodes if ep.type == 0
                ],
                airing=episode_schedule(episodes, datetime.now(CST).date()),
            )
        return result

    async def cover(self) -> dict[str, Any]:
        body = await request_body()
        subject_id = self._subject_id(body)
        # Download by subject ID; never proxy arbitrary URLs supplied by the browser.
        subject = await self.api.with_embedded_cover(
            Subject(id=subject_id, type=2, name="")
        )
        if not subject.cover_url.startswith("data:image/"):
            raise BangumiClientError("封面暂时无法下载，请稍后刷新重试")
        return {"cover_url": subject.cover_url}

    def _validated_session(self, body: dict[str, Any]) -> str:
        session_id = self._text(body, "session_id")
        parts = session_id.split(":", 2)
        if (
            len(parts) != 3
            or parts[1] not in {"GroupMessage", "FriendMessage"}
            or not parts[2].strip()
        ):
            raise ValueError("请选择群聊或私聊，并填写目标 ID")
        if parts[0] not in {platform["id"] for platform in self.platforms()}:
            raise ValueError("所选平台不在线，请先在 AstrBot 中启用对应平台")
        return session_id

    async def subscribe(self) -> dict[str, Any]:
        body = await request_body()
        session_id = self._validated_session(body)
        subject = await self.api.get_subject(self._subject_id(body))
        if subject.type != 2:
            raise ValueError("追番仅支持动画条目")
        result = await self.tracking.subscribe(session_id, subject)
        return {"created": result.created, "title": subject.title}

    async def unsubscribe(self) -> dict[str, Any]:
        body = await request_body()
        session_id = self._text(body, "session_id")
        subject_id = str(self._subject_id(body))
        removed = self.repository.unsubscribe(session_id, subject_id)
        if not removed:
            raise ValueError("该订阅已不存在，请刷新列表")
        return {"removed": True}

    async def check(self) -> dict[str, Any]:
        body = await request_body()
        raw_session = body.get("session_id")
        session_id = None
        if raw_session is not None:
            session_id = self._text(body, "session_id")
            if not self.repository.list_subscriptions(session_id):
                raise ValueError("此会话还没有订阅")
        if self.tracking._check_lock.locked() or (self._task and not self._task.done()):
            raise ValueError("已有检查正在进行，请稍后查看结果")
        if not self.repository.list_subscriptions(session_id):
            raise ValueError("还没有订阅，先添加一部喜欢的动画吧")
        job: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "started_at": datetime.now(CST).isoformat(timespec="seconds"),
            "session_id": session_id,
            "status": "running",
        }
        self.jobs.insert(0, job)
        del self.jobs[20:]
        self._task = asyncio.create_task(self._run_check(job, session_id))
        return {"job_id": job["id"]}

    async def _run_check(self, job: dict[str, Any], session_id: str | None) -> None:
        try:
            report = await self.tracking.check_updates(
                session_id=session_id, refresh=True
            )
            job.update(status="done", report=asdict(report), summary=report.summary)
        except asyncio.CancelledError:
            job.update(status="cancelled", summary="插件卸载，检查已停止")
            raise
        except Exception:
            logger.exception("WebUI 追番检查失败")
            job.update(status="error", summary="检查失败，请查看 AstrBot 日志")
        finally:
            job["finished_at"] = datetime.now(CST).isoformat(timespec="seconds")

    async def calendar(self) -> dict[str, Any]:
        days = await self.api.get_calendar()
        return {
            "days": [
                asdict(day)
                | {
                    "items": [
                        asdict(subject) | {"title": subject.title}
                        for subject in day.items
                    ]
                }
                for day in days
            ]
        }
