import asyncio
import datetime
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
    # 获取今天的星期 (1-7, Mon-Sun)
    # datetime.datetime.now().isoweekday() 返回 1-7
    today_id = datetime.datetime.now().isoweekday()

    # 寻找今天在列表中的索引
    today_index = 0
    for i, day in enumerate(calendar_data):
        if day.get("weekday", {}).get("id") == today_id:
            today_index = i
            day["is_today"] = True
            break

    # 重新排序：从今天开始，循环一周
    reordered = calendar_data[today_index:] + calendar_data[:today_index]
    return reordered


class CalendarRenderer:
    def __init__(self):
        super().__init__()
        # 设置 Jinja2 环境
        template_dir = Path(__file__).resolve().parent.parent / "templates"
        self.template_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)), autoescape=True
        )

    async def render_calendar(
        self,
        calendar_data: List[Dict[str, Any]],
        headless: bool = True,
        output_path: Optional[str] = None,
        max_retries: int = 3,
    ) -> Optional[bytes]:
        """
        渲染放送表图片。
        """
        try:
            reordered_days = reorder_days(calendar_data)
        except Exception as e:
            logger.error(f"处理日历数据失败: {e}")
            return None

        async def _render_task():
            page = await create_page()
            if not page:
                raise Exception("浏览器页面创建失败")

            try:
                # 渲染 HTML
                try:
                    template = self.template_env.get_template("calendar/calendar.html")
                    html_content = template.render(days=reordered_days)
                except Exception as e:
                    logger.error(f"Jinja2 模板渲染错误: {e}")
                    raise e

                # 处理 Base URL
                try:
                    template_file_path = (
                        Path(self.template_env.loader.searchpath[0]) / "calendar"
                    )
                    base_url = template_file_path.as_uri() + "/"

                    if "<head>" in html_content:
                        html_content = html_content.replace(
                            "<head>", f'<head><base href="{base_url}">', 1
                        )
                except Exception as e:
                    logger.warning(f"Base URL 处理失败 (可能导致样式丢失): {e}")

                try:
                    await page.set_content(
                        html_content, wait_until="networkidle", timeout=30000
                    )
                except Exception as e:
                    logger.error(f"页面内容加载超时或失败: {e}")
                    raise e

                # 等待一会儿确保图片加载（即便 networkidle 也可能有延迟）
                await asyncio.sleep(2)

                # 定位容器截图
                try:
                    container = page.locator(".container")

                    screenshot_args = {"type": "png", "omit_background": False}
                    if output_path:
                        screenshot_args["path"] = output_path

                    if await container.count() > 0:
                        image_bytes = await container.screenshot(**screenshot_args)
                    else:
                        logger.warning("未找到 .container 元素，回退到全页截图")
                        screenshot_args["full_page"] = True
                        image_bytes = await page.screenshot(**screenshot_args)
                except Exception as e:
                    logger.error(f"截图失败: {e}")
                    raise e

                return image_bytes

            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass

        try:
            return await retry(_render_task, retries=max_retries, delay=1.0)
        except Exception as e:
            logger.error(f"渲染放送表失败: {e}")
            return None
