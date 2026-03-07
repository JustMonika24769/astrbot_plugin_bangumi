from typing import cast
from urllib.parse import quote

from .base import BaseBangumiService
from .contracts import UserDetailsResponse


class UsersService(BaseBangumiService):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)

    async def get_user_details(self, username: str) -> UserDetailsResponse:
        """获取用户详细信息"""
        encoded_username = quote(username)
        url = f"{self.base_url}/v0/users/{encoded_username}"
        data = await self._request(url)
        return cast(UserDetailsResponse, data if isinstance(data, dict) else {})
