import sys
import subprocess
from astrbot.api import logger

class Renderer:
    """
    渲染器基类
    负责初始化 Playwright 环境和安装浏览器内核
    """
    def __init__(self):
        try:
            logger.info("正在检查并安装 Playwright 浏览器内核 (Chromium)...")
            # 安装 chromium 内核
            subprocess.check_call(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.info("正在检查并安装 Playwright 依赖")
            # 安装 chromium 依赖
            subprocess.check_call(
                [sys.executable, "-m", "playwright", "install-deps"]
            )
            logger.info("Playwright 浏览器内核检查完成。")
        except subprocess.CalledProcessError as e:
            logger.error(f"安装 Playwright 浏览器内核失败: {e}")
            raise e