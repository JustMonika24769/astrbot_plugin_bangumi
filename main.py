import asyncio
import tempfile
import os

import astrbot.api.message_components as Comp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.all import AstrBotConfig
from astrbot.api import logger

# 导入配置管理器
from .src.config.config_manager import ConfigManager

# 导入我们重构后的统一API类
from .src.services import BangumiService
from .src.render.subject_renderer import SubjectRenderer
from .src.render.calendar_renderer import CalendarRenderer

from typing import Any


@register(
    "astrbot_plugin_bangumi",
    "Gemini",
    "一个用于查询Bangumi条目信息的插件",
    "1.3.0",
    "https://github.com/united-pooh/astrbot_plugin_bangumi",
)
class BangumiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.config_manager = ConfigManager(config)

        self.max_fuzzy_results = 10  # 假设的默认值
        self.service = None
        try:
            # 构造代理 URL (如果配置了)
            proxy_url = None
            proxy_host = self.config_manager.get_proxy_http()
            proxy_port = self.config_manager.get_port()
            if proxy_host and proxy_port:
                # 简单的格式构造，假设是 http 代理
                proxy_url = f"{proxy_host}:{proxy_port}"

            # 初始化聚合后的API类
            self.service = BangumiService(
                access_token=self.config_manager.get_access_token(),
                user_agent=self.config_manager.get_user_agent(),
                proxy=proxy_url,
            )

        except ValueError as e:
            logger.error(f"插件初始化失败: {e}")

    async def initialize(self):
        """
        插件加载时自动运行
        自动安装web driver以及依赖
        """
        logger.info("正在检查并安装插件依赖...")
        try:
            # 安装 Playwright 系统依赖
            logger.info("正在运行 playwright install-deps...")
            process = await asyncio.create_subprocess_shell(
                "playwright install-deps",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                logger.warning(f"系统依赖安装可能失败 (非关键错误): {stderr.decode()}")
                return
            logger.info("系统依赖安装完成")

            # 安装 Playwright Chromium
            logger.info("正在安装 Playwright Chromium...")
            process = await asyncio.create_subprocess_shell(
                "playwright install chromium",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                logger.info("Playwright Chromium 安装成功")
            else:
                logger.warning(f"Playwright Chromium 安装返回错误: {stderr.decode()}")
            logger.info("Bangumi插件初始化成功")
        except Exception as e:
            logger.error(f"依赖安装流程失败: {e}")

    # --- 内部核心逻辑 ---

    async def _render_subjects(
        self, subjects: list, top_k: int = 1
    ) -> tuple[list[Comp.Image], list[str], list[str]]:
        """
        核心渲染逻辑：处理条目列表，获取详情并生成图片。

        Args:
            subjects: 条目列表，可以是包含 'id' 的字典列表，也可以是 ID 列表。
            top_k: 最大处理数量。

        Returns:
            tuple[list[Comp.Image], list[str], list[str]]:
                - 生成的图片组件列表
                - 产生的临时文件路径列表（需要调用者负责清理）
                - 成功的条目ID列表
        """
        subjects_id_list = []
        data_list = []
        temp_files = []
        # 构造第一个传入参数
        for item in subjects[:top_k]:
            subject_id = None
            if isinstance(item, dict):
                subject_id = item.get("id", None)
            if subject_id is None:
                continue
            subjects_id_list.append(subject_id)

            subject_data = await self.service.get_subject_details(subject_id)
            if len(subject_data) == 0:
                logger.warning(f"获取条目 {subject_id} 详情失败，跳过")
                continue
            data_list.append(subject_data)

            # 创建临时文件
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
            os.close(tmp_fd)  # 立即关闭文件描述符，只保留路径
            temp_files.append(tmp_path)
        
        # 创建渲染器实例
        renderer = SubjectRenderer()
        await renderer.render_batch_subject_cards(
            data_list=data_list, output_paths=temp_files
        )
        image_components = []
        try:
            for path in temp_files:
                if os.path.exists(path) and os.path.getsize(path) > 0:
                    image_components.append(Comp.Image.fromFileSystem(path))
                else:
                    logger.warning("图片生成失败")
        except Exception as e:
            logger.error(f"渲染图片失败: {e}")

        return image_components, temp_files, subjects_id_list

    async def _handle_subject(
        self,
        event: AstrMessageEvent,
        query: str,
        top_k: int | None = None,
        subject_type: list[int] | None = None,
        subject_tags: list[str] | None = None,
    ):
        """
        渲染图片全流程
        通用搜索处理逻辑：搜索 -> 渲染 -> 发送 -> 清理
        """
        if not self.service:
            yield event.plain_result("❌ 配置未完成")
            return

        if not query:
            yield event.plain_result("❌ 请提供搜索关键词")
            return

        # 处理 top_k
        if top_k is None:
            top_k = 1
        try:
            top_k = int(top_k)
        except (ValueError, TypeError):
            top_k = 1

        logger.info(f"搜索: {query}, type={subject_type}, top_k={top_k}")

        try:
            # 1. 搜索条目
            search_res = await self.service.search_subjects(
                keyword=query, subject_type=subject_type, subject_tags=subject_tags
            )
            if not search_res or "data" not in search_res or not search_res["data"]:
                yield event.plain_result("🔍 未找到相关条目")
                return

            # 2. 渲染条目
            (
                image_components,
                temp_files,
                subjects_id_list,
            ) = await self._render_subjects(search_res["data"], top_k)

            # 3. 发送图片
            if image_components:
                yield event.chain_result(image_components)
            else:
                yield event.plain_result("❌ 未能生成任何图片")

            # 4. 清理临时文件
            await asyncio.sleep(1)
            for path in temp_files:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception as e:
                    logger.warning(f"清理临时文件失败 {path}: {e}")

        except Exception as e:
            logger.error(f"处理搜索请求失败: {e}")
            yield event.plain_result(f"❌ 处理失败: {e}")

    async def _handle_calendar(
        self, event: AstrMessageEvent, api_result: list[dict[str, Any]] | None = None
    ):
        if not self.service:
            yield event.plain_result("❌ 配置未完成")
            return

        try:
            # 1. 获取每日放送
            calendar_res = await self.service.get_calendar()

            if not calendar_res:
                yield event.plain_result("❌ 未获取到放送数据")
                return

            # 2. 渲染图片
            renderer = CalendarRenderer()

            # 创建临时文件
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
            os.close(tmp_fd)

            try:
                await renderer.render_calendar(
                    calendar_res,
                    output_path=tmp_path,
                    max_retries=self.config_manager.get_max_retries(),
                )

                # 3. 发送图片
                if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                    yield event.chain_result([Comp.Image.fromFileSystem(tmp_path)])
                else:
                    yield event.plain_result("❌ 图片生成失败")

                # 4. 清理临时文件
                await asyncio.sleep(1)
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

            except Exception as e:
                logger.error(f"渲染放送表失败: {e}")
                yield event.plain_result(f"❌ 渲染失败: {e}")
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except:
                        pass

        except Exception as e:
            logger.error(f"处理每日放送失败: {e}")
            yield event.plain_result(f"❌ 处理失败: {e}")

    # --- 命令处理区 ---

    @filter.command("bgm搜索")
    async def search(
        self, event: AstrMessageEvent, query: str, top_k: int | None = None
    ):
        """
        通用搜索命令
        """
        async for result in self._handle_subject(
            event, query, top_k, subject_type=None
        ):
            yield result

    @filter.command("bgm番剧")
    async def search_anime(
        self, event: AstrMessageEvent, query: str, top_k: int | None = None
    ):
        """
        搜索番剧
        """
        async for result in self._handle_subject(
            event, query, top_k, subject_type=[2], subject_tags=["TV"]
        ):
            yield result

    @filter.command("bgm剧场版")
    async def search_movie(
        self, event: AstrMessageEvent, query: str, top_k: int | None = None
    ):
        """
        搜索剧场版
        """
        async for result in self._handle_subject(
            event, query, top_k, subject_type=[2], subject_tags=["剧场版"]
        ):
            yield result

    @filter.command("bgm漫画")
    async def search_manga(
        self, event: AstrMessageEvent, query: str, top_k: int | None = None
    ):
        """
        搜索漫画
        """
        async for result in self._handle_subject(
            event, query, top_k, subject_type=[1], subject_tags=["漫画"]
        ):
            yield result

    @filter.command("today")
    async def calender(self, event: AstrMessageEvent):
        async for result in self._handle_calendar(event):
            yield result

    @filter.command("追番")
    async def subscribe(self, event: AstrMessageEvent, query: str):
        if not self.service:
            yield event.plain_result("❌ 配置未完成")
            return

        # 获取 group_id
        group_id = None
        if hasattr(event, "message_obj") and hasattr(event.message_obj, "group_id"):
            group_id = event.message_obj.group_id

        if not group_id:
            yield event.plain_result("❌ 无法获取群组ID，请在群聊中使用")
            return

        if not query:
            yield event.plain_result("❌ 请提供番剧名称")
            return

        logger.info(f"处理追番请求: {query}, group_id={group_id}")

        try:
            # 1. 搜索条目
            search_res = await self.service.search_subjects(
                keyword=query, subject_type=[2], subject_tags=None
            )
            yield event.plain_result(str(search_res))
        except Exception as e:
            logger.error(f"处理追番请求失败: {e}")
            yield event.plain_result(f"❌ 处理失败: {e}")
