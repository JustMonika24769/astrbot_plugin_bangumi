import asyncio
import base64
from pathlib import Path
from typing import Optional, Dict, Any

import jinja2
from astrbot.api import logger

from ..utils.async_utils import retry
from ..utils.browser import create_page


class BaseRenderer:
    def __init__(self):
        # 统一模板目录定位
        self.template_dir = Path(__file__).resolve().parent.parent / "templates"
        self.template_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self.template_dir)), autoescape=True
        )

    def _generate_html(
        self, template_path: str, render_data: Dict[str, Any], sub_dir: str = ""
    ) -> str:
        """
        统一渲染模板并注入 <base> 标签。

        """
        template = self.template_env.get_template(template_path)
        html = template.render(**render_data)

        # 处理 Base URL 注入，确保静态资源加载
        base_path = self.template_dir / sub_dir if sub_dir else self.template_dir
        base_url = base_path.as_uri() + "/"

        if "<head>" in html:
            return html.replace("<head>", f'<head><base href="{base_url}">', 1)
        return f'<base href="{base_url}">{html}'

    async def _capture_screenshot(
        self,
        html_content: str,
        selector: str,
        headless: bool = True,
        timeout: int = 15000,
        wait_time: float = 0,
    ) -> Optional[str]:
        """
        通用的浏览器截图逻辑，返回 Base64 字符串。

        """
        page = await create_page(headless=headless)
        if not page:
            raise RuntimeError("无法创建浏览器页面")

        try:
            await page.set_content(
                html_content, wait_until="networkidle", timeout=timeout
            )

            if wait_time > 0:
                await asyncio.sleep(wait_time)

            args = {"type": "png", "omit_background": True}
            locator = page.locator(selector)
            screenshot_bytes = None

            if await locator.count() > 0:
                screenshot_bytes = await locator.screenshot(**args)
            else:
                logger.warning(f"未找到元素 {selector}，回退到全页截图")
                screenshot_bytes = await page.screenshot(full_page=True, type="png")

            if screenshot_bytes:
                return base64.b64encode(screenshot_bytes).decode("utf-8")
            return None
        finally:
            if page:
                await page.close()

    async def _render_to_base64(
        self,
        template_path: str,
        render_data: Dict[str, Any],
        selector: str,
        sub_dir: str = "",
        headless: bool = True,
        max_retries: int = 3,
        timeout: int = 15000,
        wait_time: float = 0,
    ) -> Optional[str]:
        """
        渲染并返回 Base64 字符串的快捷方法。

        """
        label = f"渲染 {template_path}"
        try:
            html_content = self._generate_html(template_path, render_data, sub_dir)

            return await retry(
                func=lambda: self._capture_screenshot(
                    html_content, selector, headless, timeout, wait_time
                ),
                retries=max_retries,
                label=label,
            )
        except Exception as e:
            logger.error(f"{label} 最终失败: {e}")
            return None
