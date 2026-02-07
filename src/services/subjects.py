from typing import Any, Dict

from .base import BaseBangumiService
from .schemas import Episode


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
        """
        获取条目的信息
        """
        url = f"{self.base_url}/v0/subjects/{subject_id}"
        return await self._request(url)

    async def get_subject_episodes(self, subject_id: int) -> Dict[str, Any]:
        """
        获取条目的剧集信息

        Args:
            subject_id: 条目的id
        Returns:
            data: 剧集信息
            total: 总集数
        """
        url = f"{self.base_url}/v0/episodes"
        params = {"subject_id": subject_id}
        return await self._request(url, params=params)

    async def get_latest_episode(self, subject_id: int) -> Episode | None:
        """
        从 episodes 数据中提取最新一集的集数

        :param subject_id: 条目的id

        :return: 最新一集的集数。如果没有找到有效集数,返回 None
        """
        import datetime
        from pydantic import ValidationError

        episodes_data = await self.get_subject_episodes(subject_id)

        if "data" not in episodes_data:
            return None

        current_datetime = datetime.datetime.now()
        res = None
        for episode_raw in episodes_data["data"]:
            try:
                # 使用 Pydantic 模型校验数据
                episode = Episode(**episode_raw)

                # 跳过无效的集数
                if episode.ep == 0:
                    continue

                # 检查是否已播出
                if episode.airdate:
                    try:
                        episode_airdate = datetime.datetime.strptime(
                            episode.airdate, "%Y-%m-%d"
                        ).date()
                        if episode_airdate > current_datetime.date():
                            break
                    except ValueError:
                        pass  # 日期格式错误时跳过 airdate 检查

                has_comments = episode.comment > 0

                # 判断剧集是否已发布:
                # 1. 有评论,表示实际可观看)
                # 2. 播出日期已过
                if has_comments:
                    res = episode

            except ValidationError as e:
                # 数据校验失败，记录错误并跳过该集
                from astrbot.api import logger

                logger.warning(f"Episode 数据校验失败: {e}, 原始数据: {episode_raw}")
                continue

        return res
