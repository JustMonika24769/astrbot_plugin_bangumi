import asyncio
import datetime
import base64
from pathlib import Path
from typing import Any, Dict, List, Optional

import jinja2
from astrbot.api import logger

from ..utils.async_utils import retry
from ..utils.browser import create_page


def reorder_days(calendar_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    重新排序天数，使今天排在第一位。
    """
    today_id = datetime.datetime.now().isoweekday()

    today_index = 0
    for i, day in enumerate(calendar_data):
        if day.get("weekday", {}).get("id") == today_id:
            today_index = i
            day["is_today"] = True
            break

    reordered = calendar_data[today_index:] + calendar_data[:today_index]
    return reordered


class CalendarRenderer:
    def __init__(self):
        # 设置 Jinja2 环境
        self.template_dir = Path(__file__).resolve().parent.parent / "templates"
        self.template_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self.template_dir)), autoescape=True
        )

    async def render_calendar(
        self,
        calendar_data: List[Dict[str, Any]],
        headless: bool = True,
        max_retries: int = 3,
    ) -> Optional[str]:
        """
        渲染放送表图片并返回 Base64 字符串。
        """
        try:
            reordered_days = reorder_days(calendar_data)
        except Exception as e:
            logger.error(f"处理日历数据失败: {e}")
            return None

        try:
            # 渲染 HTML
            html_content = self._generate_html(reordered_days)
        except Exception as e:
            logger.error(f"渲染日历 HTML 失败: {e}")
            return None

        # 执行截图任务 (异步逻辑，带重试)
        try:
            image_bytes = await retry(
                lambda: self._capture_screenshot(html_content, headless),
                retries=max_retries,
                delay=1.0,
            )
            if image_bytes:
                return base64.b64encode(image_bytes).decode("utf-8")
            return None
        except Exception as e:
            logger.error(f"渲染放送表在 {max_retries} 次尝试后最终失败: {e}")
            return None

    def _generate_html(self, days: List[Dict[str, Any]]) -> str:
        """
        生成 HTML 内容并注入 Base URL。
        """
        template = self.template_env.get_template("calendar/calendar.html")
        html = template.render(days=days)

        # 处理 Base URL
        base_url = (self.template_dir / "calendar").as_uri() + "/"
        if "<head>" in html:
            return html.replace("<head>", f'<head><base href="{base_url}">', 1)
        return f'<base href="{base_url}">{html}'

    @staticmethod
    async def _capture_screenshot(html_content: str, headless: bool) -> bytes:
        """
        异步辅助函数：负责浏览器操作和内存截图。
        """
        page = await create_page(headless=headless)
        if not page:
            raise RuntimeError("浏览器页面创建失败")

        try:
            await page.set_content(
                html_content, wait_until="networkidle", timeout=30000
            )

            # 等待一会儿确保图片加载
            await asyncio.sleep(2)

            # 定位容器截图
            container = page.locator(".container")
            screenshot_args = {"type": "png", "omit_background": False}

            if await container.count() > 0:
                return await container.screenshot(**screenshot_args)
            else:
                logger.warning("未找到 .container 元素，回退到全页截图")
                return await page.screenshot(full_page=True, **screenshot_args)
        finally:
            if page:
                await page.close()
