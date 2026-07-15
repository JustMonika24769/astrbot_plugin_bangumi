from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from astrbot.api import logger

from .entities import (
    CalendarDay,
    Episode,
    Subject,
    parse_iso_date,
    safe_float,
    safe_int,
)
from .plugin_config import DEFAULT_USER_AGENT


class BangumiClientError(RuntimeError):
    pass


class BangumiNotFound(BangumiClientError):
    pass


class BangumiClient:
    BASE_URL = "https://api.bgm.tv"

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        access_token: str,
        user_agent: str,
        proxy_url: str | None,
        timeout_seconds: int,
        max_retries: int,
    ) -> None:
        self.session = session
        self.proxy_url = proxy_url
        self.max_retries = max_retries
        self.timeout = aiohttp.ClientTimeout(
            total=timeout_seconds, connect=min(10, timeout_seconds)
        )
        normalized_user_agent = user_agent.strip() or DEFAULT_USER_AGENT
        self.headers = {
            "Accept": "application/json",
            "User-Agent": normalized_user_agent,
        }
        if access_token.strip():
            self.headers["Authorization"] = f"Bearer {access_token.strip()}"
        self._rate_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._cache: dict[str, tuple[float, Any]] = {}

    async def _rate_limit(self) -> None:
        async with self._rate_lock:
            remaining = 1.05 - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_request_at = time.monotonic()

    def _cached(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            self._cache.pop(key, None)
            return None
        return value

    def _remember(self, key: str, value: Any, ttl_seconds: int) -> Any:
        self._cache[key] = (time.monotonic() + ttl_seconds, value)
        return value

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.BASE_URL}{path}"
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            await self._rate_limit()
            try:
                logger.debug(
                    f"Bangumi API {method} {path} ({attempt}/{self.max_retries})"
                )
                async with self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_data,
                    headers=self.headers,
                    proxy=self.proxy_url,
                    timeout=self.timeout,
                ) as response:
                    if response.status == 404:
                        raise BangumiNotFound(f"Bangumi 条目不存在: {path}")
                    if response.status == 429 or response.status >= 500:
                        message = f"HTTP {response.status}"
                        last_error = BangumiClientError(message)
                        if attempt < self.max_retries:
                            retry_after = safe_float(
                                response.headers.get("Retry-After"), 1.5
                            )
                            await asyncio.sleep(max(1.0, retry_after))
                            continue
                    if response.status >= 400:
                        detail = (await response.text())[:300]
                        raise BangumiClientError(
                            f"Bangumi API {path} 返回 HTTP {response.status}: {detail}"
                        )
                    return await response.json()
            except BangumiNotFound:
                raise
            except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(1.5 * attempt)
                    continue
        raise BangumiClientError(f"Bangumi API 请求失败: {last_error}")

    async def get_subject(self, subject_id: int, *, refresh: bool = False) -> Subject:
        cache_key = f"subject:{subject_id}"
        if not refresh and (cached := self._cached(cache_key)) is not None:
            return cached
        payload = await self._request("GET", f"/v0/subjects/{subject_id}")
        if not isinstance(payload, dict):
            raise BangumiClientError("Bangumi 条目详情格式异常")
        subject = self._parse_subject(payload)
        return self._remember(cache_key, subject, 15 * 60)

    async def with_embedded_cover(self, subject: Subject) -> Subject:
        if subject.id <= 0:
            return subject
        cache_key = f"cover:{subject.id}"
        if (cached := self._cached(cache_key)) is not None:
            return replace(subject, cover_url=cached)
        try:
            image, content_type = await self._request_bytes(
                f"/v0/subjects/{subject.id}/image",
                params={"type": "large"},
            )
        except BangumiClientError as exc:
            logger.warning(f"获取条目 {subject.id} 封面失败: {exc}")
            return subject
        if not image:
            return subject
        mime = content_type.split(";", maxsplit=1)[0].strip()
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        data_uri = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
        self._remember(cache_key, data_uri, 60 * 60)
        return replace(subject, cover_url=data_uri)

    async def search_subjects(
        self,
        keyword: str,
        *,
        limit: int = 5,
        subject_types: tuple[int, ...] | None = None,
        tags: tuple[str, ...] | None = None,
    ) -> list[Subject]:
        normalized = keyword.strip()
        if not normalized:
            return []
        if normalized.isdigit():
            try:
                subject = await self.get_subject(int(normalized))
            except BangumiNotFound:
                return []
            if subject_types and subject.type not in subject_types:
                return []
            return [subject]

        filters: dict[str, Any] = {}
        if subject_types:
            filters["type"] = list(subject_types)
        if tags:
            filters["tag"] = list(tags)
        payload = await self._request(
            "POST",
            "/v0/search/subjects",
            json_data={
                "keyword": normalized,
                "limit": max(1, min(10, limit)),
                "offset": 0,
                "filter": filters,
            },
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            return []
        subjects: list[Subject] = []
        seen: set[int] = set()
        for item in payload["data"]:
            if not isinstance(item, dict):
                continue
            subject = self._parse_subject(item)
            if subject.id <= 0 or subject.id in seen:
                continue
            seen.add(subject.id)
            subjects.append(subject)
        return subjects

    async def _request_bytes(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> tuple[bytes, str]:
        url = f"{self.BASE_URL}{path}"
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            await self._rate_limit()
            try:
                async with self.session.get(
                    url,
                    params=params,
                    headers=self.headers,
                    proxy=self.proxy_url,
                    timeout=self.timeout,
                ) as response:
                    if response.status == 404:
                        raise BangumiNotFound(f"Bangumi 图片不存在: {path}")
                    if response.status == 429 or response.status >= 500:
                        last_error = BangumiClientError(f"HTTP {response.status}")
                        if attempt < self.max_retries:
                            await asyncio.sleep(1.5 * attempt)
                            continue
                    if response.status >= 400:
                        raise BangumiClientError(
                            f"Bangumi 图片接口返回 HTTP {response.status}"
                        )
                    return await response.read(), response.headers.get(
                        "Content-Type", "image/jpeg"
                    )
            except BangumiNotFound:
                raise
            except (aiohttp.ClientError, TimeoutError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(1.5 * attempt)
        raise BangumiClientError(f"Bangumi 图片请求失败: {last_error}")

    async def get_episodes(
        self, subject_id: int, *, refresh: bool = False
    ) -> list[Episode]:
        cache_key = f"episodes:{subject_id}"
        if not refresh and (cached := self._cached(cache_key)) is not None:
            return cached

        episodes: list[Episode] = []
        offset = 0
        page_size = 100
        while True:
            payload = await self._request(
                "GET",
                "/v0/episodes",
                params={"subject_id": subject_id, "limit": page_size, "offset": offset},
            )
            if not isinstance(payload, dict):
                break
            raw_items = payload.get("data")
            if not isinstance(raw_items, list):
                break
            episodes.extend(
                self._parse_episode(item)
                for item in raw_items
                if isinstance(item, dict)
            )
            total = safe_int(payload.get("total"), len(episodes))
            offset += len(raw_items)
            if not raw_items or offset >= total or len(raw_items) < page_size:
                break
        episodes.sort(key=lambda item: (item.sort, item.number, item.id))
        return self._remember(cache_key, episodes, 5 * 60)

    async def get_latest_aired_episode(
        self,
        subject_id: int,
        *,
        broadcast_time: str | None = None,
        refresh: bool = False,
    ) -> Episode | None:
        episodes = await self.get_episodes(subject_id, refresh=refresh)
        now = datetime.now(timezone(timedelta(hours=8)))
        for episode in reversed(episodes):
            if episode.type != 0 or episode.number <= 0:
                continue
            air_date = parse_iso_date(episode.air_date)
            if air_date:
                if air_date > now.date():
                    continue
                if air_date == now.date() and broadcast_time:
                    try:
                        hour, minute = (int(part) for part in broadcast_time.split(":"))
                        if (
                            now.time()
                            < now.replace(
                                hour=hour, minute=minute, second=0, microsecond=0
                            ).time()
                        ):
                            continue
                    except (TypeError, ValueError):
                        logger.warning(f"无效放送时间: {broadcast_time}")
                        if episode.comments <= 0:
                            continue
                elif air_date == now.date() and episode.comments <= 0:
                    continue
                return episode
            if episode.comments > 0:
                return episode
        return None

    async def get_calendar(self, *, refresh: bool = False) -> list[CalendarDay]:
        cache_key = "calendar"
        if not refresh and (cached := self._cached(cache_key)) is not None:
            return cached
        payload = await self._request("GET", "/calendar")
        if not isinstance(payload, list):
            return []
        today_id = datetime.now(timezone(timedelta(hours=8))).isoweekday()
        days: list[CalendarDay] = []
        for raw_day in payload:
            if not isinstance(raw_day, dict):
                continue
            weekday = raw_day.get("weekday", {})
            if not isinstance(weekday, dict):
                weekday = {}
            weekday_id = safe_int(weekday.get("id"))
            raw_items = raw_day.get("items", [])
            items = tuple(
                self._parse_subject(item)
                for item in raw_items
                if isinstance(item, dict)
            )
            days.append(
                CalendarDay(
                    weekday_id=weekday_id,
                    weekday_name=str(weekday.get("cn") or f"星期{weekday_id}"),
                    items=items,
                    is_today=weekday_id == today_id,
                )
            )
        days.sort(key=lambda day: day.weekday_id)
        return self._remember(cache_key, days, 30 * 60)

    @staticmethod
    def _parse_subject(data: dict[str, Any]) -> Subject:
        images = data.get("images") if isinstance(data.get("images"), dict) else {}
        rating = data.get("rating") if isinstance(data.get("rating"), dict) else {}
        tags = data.get("tags") if isinstance(data.get("tags"), list) else []
        return Subject(
            id=safe_int(data.get("id")),
            type=safe_int(data.get("type")),
            name=str(data.get("name") or ""),
            name_cn=str(data.get("name_cn") or ""),
            summary=str(data.get("summary") or ""),
            air_date=str(data.get("date") or data.get("air_date") or ""),
            platform=str(data.get("platform") or ""),
            total_episodes=safe_int(data.get("eps") or data.get("total_episodes")),
            score=safe_float(rating.get("score")),
            score_count=safe_int(rating.get("total")),
            rank=safe_int(data.get("rank")),
            cover_url=str(
                images.get("large")
                or images.get("common")
                or images.get("medium")
                or data.get("image_url")
                or ""
            ),
            tags=tuple(
                str(tag.get("name"))
                for tag in tags[:8]
                if isinstance(tag, dict) and tag.get("name")
            ),
        )

    @staticmethod
    def _parse_episode(data: dict[str, Any]) -> Episode:
        return Episode(
            id=safe_int(data.get("id")),
            subject_id=safe_int(data.get("subject_id")),
            type=safe_int(data.get("type")),
            number=safe_int(data.get("ep")),
            sort=safe_int(data.get("sort")),
            name=str(data.get("name") or ""),
            name_cn=str(data.get("name_cn") or ""),
            air_date=str(data.get("airdate") or ""),
            summary=str(data.get("desc") or ""),
            duration=str(data.get("duration") or ""),
            comments=safe_int(data.get("comment")),
        )
