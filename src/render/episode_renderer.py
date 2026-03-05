from .base_renderer import BaseRenderer
from ..services import Episode, RenderData


class EpisodeRenderer(BaseRenderer):
    async def render_episode(
        self,
        episode_data: Episode,
        rpc_url: str | None = None,
        headless: bool = True,
        max_retries: int = 3,
    ) -> str | None:
        """
        渲染单集信息卡片并返回 Base64 编码的图片字符串。

        """
        # 数据转换
        render_data: RenderData = episode_data.model_dump()

        return await self.render(
            template_path="update/episode.html",
            render_data=render_data,
            selector="#card-container",
            rpc_url=rpc_url,
            headless=headless,
            max_retries=max_retries,
        )
