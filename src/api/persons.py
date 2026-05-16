from typing import cast

from ..bangumi_types import JsonObject
from ..domain.contracts import PersonDetailsResponse, PersonsSearchResponse
from .base import BaseBangumiService


class PersonsService(BaseBangumiService):
    async def search_persons(
        self, keyword: str, limit: int = 10
    ) -> PersonsSearchResponse:
        """通过关键词搜索人物"""
        url = f"{self.base_url}/v0/search/persons"
        json_data: JsonObject = {"keyword": keyword}
        params = {"limit": limit}
        data = await self._request(
            url, method="POST", json_data=json_data, params=params
        )
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return cast(PersonsSearchResponse, data)
        return {"data": []}

    async def get_person_details(self, person_id: int) -> PersonDetailsResponse:
        """获取单个人物的详细信息"""
        url = f"{self.base_url}/v0/persons/{person_id}"
        data = await self._request(url)
        return cast(PersonDetailsResponse, data if isinstance(data, dict) else {})
