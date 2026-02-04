from typing import Any, Dict
from urllib.parse import quote

from .base import BaseBangumiService


class UsersService(BaseBangumiService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def get_user_details(self, username: str) -> Dict[str, Any]:
        """获取用户详细信息"""
        encoded_username = quote(username)
        url = f"{self.base_url}/v0/users/{encoded_username}"
        return await self._request(url)
