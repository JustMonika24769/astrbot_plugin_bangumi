import asyncio
import os
import sys
from astrbot.api import logger


class EnvManager:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.flag_file = os.path.join(
            data_dir, "plugin_data", "astrbot_plugin_bangumi", ".playwright_installed"
        )

    async def verify_playwright(self) -> bool:
        """
        验证 Playwright 是否安装成功并可运行。
        """
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
                await browser.close()
            return True
        except Exception as e:
            logger.debug(f"Playwright 环境验证失败: {e}")
            return False

    async def install_dependencies(self):
        """
        安装 Playwright 及其 Chromium 浏览器。
        """
        logger.info("正在初始化插件依赖 (Playwright)...")
        try:
            # 1. 安装 Playwright 系统依赖 (仅限 Linux)
            if sys.platform == "linux":
                logger.info("正在运行 playwright install-deps...")
                env = os.environ.copy()
                env["DEBIAN_FRONTEND"] = "noninteractive"

                process = await asyncio.create_subprocess_shell(
                    f"{sys.executable} -m playwright install-deps",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=env,
                )

                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    msg = line.decode().strip()
                    if msg:
                        logger.info(f"[Playwright] {msg}")

                await process.wait()
                if process.returncode != 0:
                    logger.warning(
                        f"系统依赖安装返回状态码: {process.returncode} (可能由于非 root 权限)"
                    )
            else:
                logger.info(
                    f"当前系统为 {sys.platform}，跳过系统依赖安装 (install-deps)。"
                )

            # 2. 安装 Playwright Chromium
            logger.info("正在安装 Playwright Chromium...")
            process = await asyncio.create_subprocess_shell(
                f"{sys.executable} -m playwright install chromium",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                msg = line.decode().strip()
                if msg:
                    logger.info(f"[Playwright] {msg}")

            await process.wait()

            if process.returncode == 0:
                if await self.verify_playwright():
                    logger.info("Playwright Chromium 安装并验证成功")
                    os.makedirs(os.path.dirname(self.flag_file), exist_ok=True)
                    with open(self.flag_file, "w") as f:
                        f.write("installed")
                else:
                    logger.error(
                        "Playwright 安装后验证依然失败，请检查网络或手动安装依赖。"
                    )
            else:
                logger.warning(
                    f"Playwright Chromium 安装返回错误码: {process.returncode}"
                )

        except Exception as e:
            logger.error(f"依赖安装流程失败: {e}")

    def is_installed(self) -> bool:
        """检查标记文件是否存在"""
        return os.path.exists(self.flag_file)
