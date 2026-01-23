import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import jinja2
from astrbot.api import logger

from ..utils.async_utils import retry
from ..utils.browser import create_page


def preprocess_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """预处理数据以适配模板"""
    processed = data.copy()

    # 处理图片 URL
    if "image_url" not in processed:
        images = processed.get("images", {})
        if images:
            processed["image_url"] = (
                images.get("large")
                or images.get("common")
                or images.get("medium")
                or ""
            )

    # 处理日期
    if "date" not in processed and "air_date" in processed:
        processed["date"] = processed["air_date"]

    # 处理类型映射
    if "platform" not in processed and "type" in processed:
        type_map = {
            1: "书籍",
            2: "动画",
            3: "音乐",
            4: "游戏",
            6: "三次元",
        }
        # 确保 type 是 int，防止 API 变动返回 string
        try:
            type_id = int(processed["type"])
            processed["platform"] = type_map.get(type_id, "未知")
        except (ValueError, TypeError):
            processed["platform"] = "未知"

    return processed


class SubjectRenderer:
    def __init__(self):
        # 设置 Jinja2 环境
        # 使用 resolve() 获取绝对路径，并转为 str 传给 FileSystemLoader 以保证兼容性
        template_dir = Path(__file__).resolve().parent.parent / "templates"
        self.template_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)), autoescape=True
        )

    async def render_batch_subject_cards(
        self,
        data_list: List[Dict[str, Any]],
        output_paths: List[str],
        headless: bool = True,
        wait_time: int = 0,
        max_retries: int = 3,
    ) -> None:
        """
        批量渲染条目卡片。
        通过循环调用单张渲染函数实现。
        """
        for data, output_path in zip(data_list, output_paths):
            try:
                await self.render_subject_card(
                    data=data,
                    output_path=output_path,
                    headless=headless,
                    wait_time=wait_time,
                    max_retries=max_retries,
                )
                # render_subject_card 成功时返回条目id，失败时返回空字符串
            except Exception as e:
                logger.error(f"批量处理其中一个条目时发生未知错误: {e}")

    async def render_subject_card(
        self,
        data: Dict[str, Any],
        headless: bool = True,
        output_path: str | None = None,
        wait_time: int = 0,
        max_retries: int = 3,
    ) -> None:
        """
        将条目卡片渲染为图片。
        返回渲染条目的id
        """
        # 预处理数据
        render_data = preprocess_data(data)

        async def _render_task() -> None:
            page = await create_page()
            try:
                # 渲染 HTML
                template = self.template_env.get_template("subject/subject.html")
                html_content = template.render(**render_data)
                # 获取模板文件的父目录作为 base_url，以便正确解析相对路径（如 CSS/JS）
                template_file_path = (
                    Path(self.template_env.loader.searchpath[0]) / "subject"
                )
                base_url = template_file_path.as_uri() + "/"

                # 注入 <base> 标签以解决相对路径问题
                if "<head>" in html_content:
                    html_content = html_content.replace(
                        "<head>", f'<head><base href="{base_url}">', 1
                    )

                try:
                    await page.set_content(
                        html_content, wait_until="networkidle", timeout=15000
                    )
                except TimeoutError as timeout_error:
                    logger.warning(
                        f"等待页面加载时发生超时或错误，尝试继续截图: {timeout_error}"
                    )

                # 额外等待（如果指定）
                if wait_time > 0:
                    logger.info(f"等待 {wait_time} 秒后关闭浏览器...")
                    await asyncio.sleep(wait_time)

                # 定位卡片元素
                card_locator = page.locator("#card")

                # 截图参数
                screenshot_args = {"type": "png", "omit_background": True}
                if output_path:
                    screenshot_args["path"] = output_path

                # 检查元素是否存在并截图
                if await card_locator.count() > 0:
                    await card_locator.screenshot(**screenshot_args)
                else:
                    logger.warning("未找到 #card 元素，进行全页截图")
                    screenshot_args["full_page"] = True
                    if "omit_background" in screenshot_args:
                        del screenshot_args["omit_background"]
                    await page.screenshot(**screenshot_args)
            finally:
                # 确保资源释放
                if page is not None:
                    await page.close()

        # 使用基类的重试机制执行渲染任务
        try:
            await retry(_render_task, retries=max_retries, delay=1.0)
        except Exception as e:
            logger.error(f"渲染最终失败: {e}")
