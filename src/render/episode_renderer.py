import asyncio
import base64
from pathlib import Path
from typing import Optional, Dict, Any

import jinja2
from astrbot.api import logger
from pydantic import BaseModel

from ..utils.async_utils import retry
from ..utils.browser import create_page
from ..services.schemas import Episode


class EpisodeRenderer:
    def __init__(self):
        self.template_dir = Path(__file__).resolve().parent.parent / "templates"
        self.template_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self.template_dir)), autoescape=True
        )

    async def render_episode(
        self,
        episode_data: Episode,
        headless: bool = True,
        max_retries: int = 3,
    ) -> str | None:
        """
        渲染单集信息卡片并返回 Base64 编码的图片字符串。
        不再写入本地文件，以避免资源清理问题。
        """
        # 数据转换
        render_data = (
            episode_data.model_dump()
            if isinstance(episode_data, BaseModel)
            else episode_data
        )

        try:
            # 渲染 HTML (同步逻辑)
            html_content = self._generate_html(render_data)
        except Exception as e:
            logger.error(f"Jinja2 模板渲染失败: {e}")
            return None

        # 执行截图任务 (异步逻辑，带重试)
        try:
            image_bytes = await retry(
                lambda: self._capture_screenshot(html_content, headless),
                retries=max_retries,
                delay=1.0,
            )
            if image_bytes:
                # 转换为 base64 字符串
                return base64.b64encode(image_bytes).decode("utf-8")
            return None
        except Exception as e:
            logger.error(f"单集卡片渲染在 {max_retries} 次尝试后最终失败: {e}")
            return None

    def _generate_html(self, data: Dict[str, Any]) -> str:
        """
        同步辅助函数：负责模板渲染和 HTML 静态路径处理。
        """
        template = self.template_env.get_template("update/episode2.html")
        html = template.render(**data)

        # 注入 <base> 标签，确保 HTML 能找到本地 CSS/图片等资源
        base_url = self.template_dir.as_uri() + "/"
        if "<head>" in html:
            return html.replace("<head>", f'<head><base href="{base_url}">', 1)
        return f'<base href="{base_url}">{html}'

    @staticmethod
    async def _capture_screenshot(html_content: str, headless: bool) -> bytes:
        """
        异步辅助函数：仅负责 Playwright 浏览器操作和内存截图。
        """
        page = await create_page(headless=headless)
        if not page:
            raise RuntimeError("无法创建浏览器页面")

        try:
            await page.set_content(
                html_content, wait_until="networkidle", timeout=15000
            )

            screenshot_args = {"type": "png", "omit_background": True}

            # 尝试定位 #card-container 容器进行局部截图，若不存在则全页截图
            card_locator = page.locator("#card-container")
            if await card_locator.count() > 0:
                return await card_locator.screenshot(**screenshot_args)

            return await page.screenshot(full_page=True, **screenshot_args)
        finally:
            if page:
                await page.close()
