from typing import Optional
from pydantic import BaseModel
from .base_renderer import BaseRenderer
from ..services.schemas import Episode


class EpisodeRenderer(BaseRenderer):
    async def render_episode(
        self,
        episode_data: Episode,
        headless: bool = True,
        max_retries: int = 3,
    ) -> Optional[str]:
        """
        渲染单集信息卡片并返回 Base64 编码的图片字符串。

        """
        # 数据转换
        render_data = (
            episode_data.model_dump()
            if isinstance(episode_data, BaseModel)
            else episode_data
        )

        return await self._render_to_base64(
            template_path="update/episode2.html",
            render_data=render_data,
            selector="#card-container",
            headless=headless,
            max_retries=max_retries,
        )
