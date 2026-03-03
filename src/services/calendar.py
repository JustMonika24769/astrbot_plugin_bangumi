from typing import Any

from astrbot.api import logger

from .base import BaseBangumiService


class CalendarService(BaseBangumiService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def get_calendar(self) -> list[dict[str, Any]]:
        url = f"{self.base_url}/calendar"
        data = await self._request(url, method="GET")

        if not isinstance(data, list):
            logger.warning(f"get_calendar 返回了非 list 类型: {type(data)}")
            return []

        if data and not isinstance(data[0], dict):
            logger.warning(f"get_calendar 列表元素类型异常: {type(data[0])}")
            return []

        return data
