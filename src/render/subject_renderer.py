import os
from pathlib import Path
from typing import Dict, Any, Optional
import jinja2
from playwright.async_api import async_playwright
from astrbot.api import logger

class SubjectRenderer:
    def __init__(self):
        # 设置 Jinja2 环境
        template_dir = Path(__file__).parent.parent / "templates"
        self.template_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(template_dir),
            autoescape=True
        )

    def _preprocess_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """预处理数据以适配模板"""
        processed = data.copy()
        
        # 处理图片 URL
        if "image_url" not in processed:
            images = processed.get("images", {})
            if images:
                processed["image_url"] = images.get("large") or images.get("common") or images.get("medium") or ""
        
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
            processed["platform"] = type_map.get(processed["type"], "未知")
        
        return processed

    async def render_subject_card(self, data: Dict[str, Any], headless: bool = True, output_path: Optional[str] = None) -> Optional[bytes]:
        """
        将条目卡片渲染为图片。
        :param data: 包含条目数据的字典（标题、图片 URL、摘要等）
        :param headless: 是否以无头模式运行浏览器。默认为 True。
        :param output_path: (可选) 图片保存路径。如果提供，将图片保存到该路径。
        :return: 图片字节 (PNG) 或如果失败则返回 None
        """
        playwright = None
        browser = None
        try:
            # 预处理数据
            render_data = self._preprocess_data(data)

            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=headless)
            
            context = await browser.new_context(
                viewport={"width": 960, "height": 540},
                device_scale_factor=3
            )
            page = await context.new_page()

            # 渲染 HTML
            template = self.template_env.get_template("subject/subject.html")
            html_content = template.render(**render_data)

            # 加载到页面
            await page.set_content(html_content)
            
            # 等待图片和字体加载
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                logger.warning("Timeout waiting for network idle, proceeding with screenshot")

            # 定位卡片元素
            card_locator = page.locator("#card")
            
            # 专门对卡片元素进行截图
            screenshot_args = {"type": "png", "omit_background": True}
            if output_path:
                screenshot_args["path"] = output_path

            if await card_locator.count() > 0:
                screenshot = await card_locator.screenshot(**screenshot_args)
            else:
                if output_path:
                     screenshot_args["full_page"] = True
                     del screenshot_args["omit_background"] # full_page incompatible with omit_background usually? lets just keep simple
                screenshot = await page.screenshot(type="png", full_page=True, path=output_path if output_path else None)

            return screenshot
        except Exception as e:
            logger.error(f"{e}")
            