import asyncio
import base64
import json
from pathlib import Path
from typing import Optional, Dict, Any

import jinja2
import aiohttp
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
        通用的本地浏览器截图逻辑，返回 Base64 字符串。
        """
        page = await create_page(headless=headless)
        if not page:
            raise RuntimeError("[-] 无法创建浏览器页面")

        try:
            await page.set_content(html_content, wait_until="load", timeout=timeout)

            if wait_time > 0:
                await asyncio.sleep(wait_time)

            args = {"type": "png", "omit_background": True}
            locator = page.locator(selector)
            screenshot_bytes = None

            if await locator.count() > 0:
                screenshot_bytes = await locator.screenshot(**args)
            else:
                logger.warning(f"[+] 未找到元素 {selector}，回退到全页截图")
                screenshot_bytes = await page.screenshot(full_page=True, type="png")

            if screenshot_bytes:
                return base64.b64encode(screenshot_bytes).decode("utf-8")
            return None
        finally:
            if page:
                await page.close()

    async def _render_via_rpc(
        self,
        rpc_url: str,
        html_content: str,
        selector: str,
        timeout: int = 30000,
        wait_time: float = 0,
    ) -> Optional[str] | None:
        """
        通过 RPC-JSON 服务器渲染并返回 Base64 字符串。
        """
        if not rpc_url:
            return None

        payload = {
            "jsonrpc": "2.0",
            "method": "screenshot",
            "params": {
                "html": html_content,
                "selector": selector,
                "wait_time": wait_time,
                "timeout": timeout,
                "scale": 3,
            },
            "id": int(asyncio.get_event_loop().time() * 1000),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    rpc_url, json=payload, timeout=timeout
                ) as response:
                    if response.status != 200:
                        logger.error(
                            f"[-] RPC 渲染服务器返回错误状态码: {response.status}"
                        )
                        return None

                    result = await response.json()
                    if "error" in result:
                        logger.error(f"[-] RPC 渲染失败: {result['error']}")
                        return None
                    result = result.get("result")
                    if "image" in result:
                        return result["image"]
                    return None
        except Exception as e:
            logger.error(f"[-] RPC 渲染请求发生异常: {e}")
            return None

    async def _render_locally(
        self,
        html_content: str,
        template_path: str,
        selector: str,
        headless: bool = True,
        max_retries: int = 3,
        timeout: int = 15000,
        wait_time: float = 0,
    ) -> Optional[str]:
        """
        本地渲染并返回 Base64 字符串的快捷方法。
        """
        label = f"[+] 本地渲染 {template_path}"
        try:
            return await retry(
                func=lambda: self._capture_screenshot(
                    html_content, selector, headless, timeout, wait_time
                ),
                retries=max_retries,
                label=label,
            )
        except Exception as e:
            logger.error(f"[-] {label} 最终失败: {e}")
            return None

    async def render(
        self,
        template_path: str,
        render_data: Dict[str, Any],
        selector: str,
        rpc_url: Optional[str] = None,
        sub_dir: str = "",
        timeout: int = 30000,
        wait_time: float = 0,
        **kwargs,
    ) -> Optional[str]:
        """
        通用渲染方法：优先尝试 RPC 渲染，若失败或未配置则回退到本地渲染。

        Args:
            template_path: 模板路径
            render_data: 渲染数据
            selector: 截图元素的 CSS 选择器
            rpc_url: RPC 服务器地址
            sub_dir: 模板子目录（用于 base 标签注入）
            timeout: 超时时间（毫秒）
            wait_time: 截图前的等待时间（秒）
            **kwargs: 传递给 _render_locally 的额外参数（如 headless, max_retries）
        """
        html_content = self._generate_html(template_path, render_data, sub_dir)

        if rpc_url:
            logger.debug(f"[+] 尝试通过 RPC 渲染: {template_path}")
            result = await self._render_via_rpc(
                rpc_url=rpc_url,
                html_content=html_content,
                selector=selector,
                timeout=timeout,
                wait_time=wait_time,
            )
            if result:
                return result
            logger.warning(f"[-] RPC 渲染失败 ({template_path})，正在回退到本地渲染...")
            logger.error(f"[-] 错误信息({result})")

        return await self._render_locally(
            html_content=html_content,
            template_path=template_path,
            selector=selector,
            timeout=timeout,
            wait_time=wait_time,
            **kwargs,
        )
