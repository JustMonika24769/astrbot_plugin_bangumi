import datetime
import base64
from typing import Any, Dict, List, Optional
from pydantic import ValidationError
from astrbot.api import logger

from .base import BaseBangumiService
from .schemas import Episode
from .types import ImageSize


class SubjectsService(BaseBangumiService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def search_subjects(
        self,
        keyword: str,
        limit: int = 5,
        offset: int = 0,
        subject_type: List[int] | None = None,
        subject_tags: List[str] | None = None,
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

    async def get_subject_image(self, subject_id: str, size: ImageSize) -> bytes:
        """
        获取条目的图片原始二进制数据
        """
        url = f"{self.base_url}/v0/subjects/{subject_id}/image"
        params = {"type": size.value}
        return await self._request(url, params=params, is_json=False)

    async def get_subject_base64image(
        self, subject_id: str, size: ImageSize
    ) -> Optional[str]:
        """
        获取条目的图片并转换为 Base64 编码的字符串
        """
        try:
            image_bytes = await self.get_subject_image(subject_id, size)
            if image_bytes:
                return base64.b64encode(image_bytes).decode("utf-8")
        except Exception as e:
            logger.error(f"获取条目 {subject_id} 的 Base64 图片失败: {e}")
        return None

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

    async def get_latest_episode(self, subject_id: int) -> Optional[Episode]:
        """
        从 episodes 数据中提取最新一集的信息。
        最新一集的定义：已播出且有互动（评论）的普通剧集。
        """
        episodes_data = await self.get_subject_episodes(subject_id)
        raw_list = episodes_data.get("data", [])
        if not raw_list:
            return None

        # 解析并校验数据
        episodes = self._parse_episodes(raw_list)

        # 获取今天的日期用于比较
        today = datetime.date.today()

        # 逆序查找：从最后一集向前找第一个符合条件的
        for episode in reversed(episodes):
            if episode.ep == 0:
                continue

            # 检查播出状态
            is_aired = True
            if episode.airdate:
                try:
                    episode_date = datetime.datetime.strptime(
                        episode.airdate, "%Y-%m-%d"
                    ).date()
                    is_aired = episode_date <= today
                except ValueError:
                    # 日期格式异常时，不因为日期判定为未播出
                    pass

            # 核心业务逻辑：已播出且有评论互动
            if is_aired and episode.comment > 0:
                return episode

        return None

    @staticmethod
    def _parse_episodes(raw_data: List[Dict[str, Any]]) -> List[Episode]:
        """
        辅助函数：将原始字典列表解析为 Episode 模型列表，自动过滤校验失败的数据。
        """
        parsed_episodes = []
        for item in raw_data:
            try:
                parsed_episodes.append(Episode(**item))
            except ValidationError as e:
                logger.warning(f"解析剧集数据失败，已跳过: {e}, 原始数据: {item}")
        return parsed_episodes
