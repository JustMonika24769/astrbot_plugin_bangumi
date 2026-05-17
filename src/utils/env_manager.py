import asyncio
import json
import os
import sys
from pathlib import Path
from typing import cast

from astrbot.api import logger


def _read_env_values(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


class EnvManager:
    def __init__(self, data_dir: str) -> None:
        self.data_dir = data_dir
        self.flag_file = os.path.join(data_dir, ".playwright_installed")
        self.font_dir = os.path.join(data_dir, "fonts")

    @staticmethod
    def generate_env_from_schema(
        schema_path: str | Path,
        env_path: str | Path,
        *,
        preserve_existing: bool = True,
        render_mode_default: str | None = None,
    ) -> None:
        schema_file = Path(schema_path)
        env_file = Path(env_path)
        raw_schema = json.loads(schema_file.read_text(encoding="utf-8"))
        if not isinstance(raw_schema, dict):
            raise ValueError("配置 schema 必须是 JSON 对象")

        schema = cast(dict[str, object], raw_schema)
        existing_values = _read_env_values(env_file) if preserve_existing else {}
        lines = [
            "# Generated from _conf_schema.json for local testing.",
            "# Fill access_token before running integration tests that hit Bangumi APIs.",
            "",
        ]

        for key, raw_item in schema.items():
            if not isinstance(raw_item, dict):
                continue
            item = cast(dict[str, object], raw_item)
            value = existing_values.get(key)
            if value is None:
                default = item.get("default", "")
                value = str(default) if default is not None else ""
                if key == "render_mode" and render_mode_default is not None:
                    value = render_mode_default
            lines.append(f"{key}={value}")

        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    async def verify_playwright(self) -> bool:
        """
        验证 Playwright 是否安装成功并可运行
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

    async def install_dependencies(self) -> None:
        """
        安装 Playwright 及其 Chromium 浏览器
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

                stdout = process.stdout
                if stdout is not None:
                    while True:
                        line = await stdout.readline()
                        if not line:
                            break
                        msg = line.decode().strip()
                        if msg:
                            logger.info(f"[Playwright] {msg}")
                else:
                    logger.warning("playwright install-deps 未返回输出流")

                await process.wait()
                if process.returncode != 0:
                    logger.warning(
                        f"系统依赖安装返回状态码: {process.returncode} (可能由于非 root 权限)"
                    )
            else:
                logger.info(
                    f"当前系统为 {sys.platform},跳过系统依赖安装 (install-deps)"
                )

            # 2. 安装 Playwright Chromium
            logger.info("正在安装 Playwright Chromium...")
            process = await asyncio.create_subprocess_shell(
                f"{sys.executable} -m playwright install chromium",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            stdout = process.stdout
            if stdout is not None:
                while True:
                    line = await stdout.readline()
                    if not line:
                        break
                    msg = line.decode().strip()
                    if msg:
                        logger.info(f"[Playwright] {msg}")
            else:
                logger.warning("playwright install chromium 未返回输出流")

            await process.wait()

            if process.returncode == 0:
                if await self.verify_playwright():
                    logger.info("Playwright Chromium 安装并验证成功")
                    os.makedirs(os.path.dirname(self.flag_file), exist_ok=True)
                    with open(self.flag_file, "w", encoding="utf-8") as f:
                        f.write("installed")
                else:
                    logger.error(
                        "Playwright 安装后验证依然失败,请检查网络或手动安装依赖"
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

    def start_font_download(self) -> None:
        """在后台线程预热 Pillow 所需字体,不阻塞插件初始化。"""
        from ..render.pillow_utils import start_font_download

        start_font_download(self.font_dir)
