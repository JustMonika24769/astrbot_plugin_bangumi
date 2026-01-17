from typing import Dict, Any
from .base import BaseBangumiService


class CalendarService(BaseBangumiService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def calendar(self) -> Dict[str, Any]:
        url = f"{self.base_url}/calendar"
        data = await self._request(url, method="GET")
        return data
