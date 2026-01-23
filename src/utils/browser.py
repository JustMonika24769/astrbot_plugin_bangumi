from astrbot.api import logger
from playwright.async_api import async_playwright
from playwright.async_api import ViewportSize


async def create_page(
    headless: bool = True,
    width: int = 1024,
    height: int = 768,
    scale_factor: int = 3,
):
    try:
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

        # 创建上下文
        context = await browser.new_context(
            viewport=ViewportSize(width=width, height=height),
            device_scale_factor=scale_factor,
            is_mobile=False,
            has_touch=False,
        )
        page = await context.new_page()
        __original_close = page.close

        async def close_all(*args, **kwargs):
            page.close = __original_close
            try:
                await browser.close()
                await playwright.stop()
            except Exception as e:
                logger.error(f"唔…关闭页面的时候出错了{e}")

        page.close = close_all
        return page
    except Exception as e:
        logger.error(f"初始化浏览器失败:{e}")
        return None
