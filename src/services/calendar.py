import asyncio
import copy
import time
from typing import cast

from astrbot.api import logger

from .base import BaseBangumiService
from .contracts import CalendarDay
from .exceptions import BangumiApiError


class CalendarService(BaseBangumiService):
    CALENDAR_CACHE_TTL_SECONDS = 12 * 60 * 60

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._calendar_cache: list[CalendarDay] | None = None
        self._calendar_cache_expire_at: float = 0.0
        self._calendar_cache_lock = asyncio.Lock()

    def _is_calendar_cache_valid(self, now: float) -> bool:
        return self._calendar_cache is not None and now < self._calendar_cache_expire_at

    def invalidate_calendar_cache(self) -> None:
        self._calendar_cache = None
        self._calendar_cache_expire_at = 0.0

    async def get_calendar(self) -> list[CalendarDay]:
        now = time.time()
        if self._is_calendar_cache_valid(now):
            return copy.deepcopy(self._calendar_cache)

        # 双重检查 + 锁，避免并发下重复请求远端 API
        async with self._calendar_cache_lock:
            now = time.time()
            if self._is_calendar_cache_valid(now):
                return copy.deepcopy(self._calendar_cache)

            url = f"{self.base_url}/calendar"
            previous_cache = copy.deepcopy(self._calendar_cache)
            try:
                data = await self._request(url, method="GET")
            except (BangumiApiError, RuntimeError, ValueError, TypeError) as e:
                logger.error(f"get_calendar 刷新缓存失败: {e}")
                if previous_cache is not None:
                    return previous_cache
                return []

            if not isinstance(data, list):
                logger.warning(f"get_calendar 返回了非 list 类型: {type(data)}")
                if previous_cache is not None:
                    return previous_cache
                return []

            normalized: list[CalendarDay] = []
            for item in data:
                if isinstance(item, dict):
                    normalized.append(cast(CalendarDay, item))
                else:
                    logger.warning(f"get_calendar 列表元素类型异常: {type(item)}")

            self._calendar_cache = copy.deepcopy(normalized)
            self._calendar_cache_expire_at = now + self.CALENDAR_CACHE_TTL_SECONDS
            return copy.deepcopy(self._calendar_cache)
