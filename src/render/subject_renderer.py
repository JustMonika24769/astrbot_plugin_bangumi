import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
import jinja2
from playwright.async_api import async_playwright
from astrbot.api import logger
from .renderer import Renderer

class SubjectRenderer(Renderer):
    def __init__(self):
        super().__init__()
        # 设置 Jinja2 环境
        # 使用 resolve() 获取绝对路径，并转为 str 传给 FileSystemLoader 以保证兼容性
        template_dir = Path(__file__).resolve().parent.parent / "templates"
        self.template_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)), autoescape=True
        )

    def _preprocess_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
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

    async def render_subject_card(
        self,
        data: Dict[str, Any],
        headless: bool = True,
        output_path: Optional[str] = None,
        wait_time: int = 0,
    ) -> Optional[bytes]:
        """
        将条目卡片渲染为图片。
        """
        playwright = None
        browser = None
        context = None
        page = None

        try:
            # 预处理数据
            render_data = self._preprocess_data(data)
            
            # 启动 Playwright
            playwright = await async_playwright().start()

            # 浏览器启动参数，适配 Docker 环境
            chrome_args = [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-first-run",
                "--disable-extensions",
                "--disable-default-apps",
            ]

            browser = await playwright.chromium.launch(
                headless=headless,
                args=chrome_args,
            )

            # 创建页面上下文，设置高分屏参数
            context = await browser.new_context(
                viewport={"width": 1024, "height": 768},
                device_scale_factor=3,
                is_mobile=False,
                has_touch=False
            )
            
            page = await context.new_page()

            # 渲染 HTML
            template = self.template_env.get_template("subject/subject.html")
            html_content = template.render(**render_data)

            # 加载到页面
            # wait_until="networkidle" 表示网络空闲（默认是 500ms 内没有新的网络请求）
            try:
                await page.set_content(
                    html_content, 
                    wait_until="networkidle", 
                    timeout=15000 
                )
            except Exception as e:
                logger.warning(f"等待页面加载时发生超时或错误，尝试继续截图: {e}")

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

            image_bytes = None
            # 检查元素是否存在并截图
            if await card_locator.count() > 0:
                image_bytes = await card_locator.screenshot(**screenshot_args)
            else:
                logger.warning("未找到 #card 元素，进行全页截图")
                screenshot_args["full_page"] = True
                if "omit_background" in screenshot_args:
                    del screenshot_args["omit_background"]
                image_bytes = await page.screenshot(**screenshot_args)

            return image_bytes

        except Exception as e:
            logger.error(f"渲染错误: {e}")
            return None
            
        finally:
            # 确保资源释放
            if page:
                await page.close()
            if context:
                await context.close()
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()