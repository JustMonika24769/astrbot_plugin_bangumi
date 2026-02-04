from typing import Any, Dict

from .base import BaseBangumiService


class SubjectsService(BaseBangumiService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.type_map = {
            1: "📚 书籍",
            2: "🎬 动画",
            3: "🎵 音乐",
            4: "🎮 游戏",
            6: "🌐 三次元",
        }

    async def search_subjects(
        self,
        keyword: str,
        limit: int = 5,
        offset: int = 0,
        subject_type: list[int] | None = None,
        subject_tags: list[str] | None = None,
    ) -> Dict[str, Any]:
        cache_key = f"search:{keyword}:{limit}"
        if cache_key in self.search_cache:
            return self.search_cache[cache_key]

        url = f"{self.base_url}/v0/search/subjects"
        json_data: dict[str, Any] = {
            "keyword": keyword,
            "limit": limit,
            "offset": offset,
            "filter": {},
        }
        if subject_type is not None:
            json_data["filter"]["type"] = subject_type
        if subject_tags is not None:
            json_data["filter"]["tag"] = subject_tags
        data = await self._request(
            url,
            method="POST",
            json_data=json_data,
        )
        return data

    async def get_subject_details(self, subject_id: int) -> Dict[str, Any]:
        url = f"{self.base_url}/v0/subjects/{subject_id}"
        return await self._request(url)
