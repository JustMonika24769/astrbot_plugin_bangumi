from typing import Any, Dict

from .base import BaseBangumiService


class PersonsService(BaseBangumiService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # --- 新增人物相关方法 ---

    async def search_persons(self, keyword: str, limit: int = 10) -> Dict[str, Any]:
        """通过关键词搜索人物"""
        url = f"{self.base_url}/v0/search/persons"
        json_data = {"keyword": keyword}
        params = {"limit": limit}
        return await self._request(
            url, method="POST", json_data=json_data, params=params
        )

    async def get_person_details(self, person_id: int) -> Dict[str, Any]:
        """获取单个人物的详细信息"""
        url = f"{self.base_url}/v0/persons/{person_id}"
        return await self._request(url)
