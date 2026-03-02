import asyncio
import os
import sys
import tempfile
import datetime
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.all import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register, StarTools
from .src.services.schemas import Episode

# 导入配置管理器
from .src.config.config_manager import ConfigManager
from .src.render.calendar_renderer import CalendarRenderer
from .src.render.subject_renderer import SubjectRenderer
from .src.render.episode_renderer import EpisodeRenderer
from .src.utils.scheduler import SchedulerManager

# 导入我们重构后的逻辑服务
from .src.services import BangumiService
from .src.services.subscription import SubscriptionService
from .src.services.types import ImageSize
from .src.db import BangumiRepository


@register(
    "astrbot_plugin_bangumi",
    "Gemini",
    "一个用于查询Bangumi条目信息的插件",
    "1.3.0",
    "https://github.com/united-pooh/astrbot_plugin_bangumi",
)
class BangumiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        """
        初始化 BangumiPlugin 插件。
        """
        super().__init__(context)
        self.config = config
        self.config_manager = ConfigManager(config)
        self.scheduler_manager = SchedulerManager()
        self.max_fuzzy_results = 10

        # 1. 优先初始化核心依赖
        try:
            self.storage = BangumiRepository()
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            self.storage = None

        self.service = None
        try:
            proxy_url = None
            proxy_host = self.config_manager.get_proxy_http()
            proxy_port = self.config_manager.get_port()
            if proxy_host and proxy_port:
                proxy_url = f"{proxy_host}:{proxy_port}"

            self.service = BangumiService(
                access_token=self.config_manager.get_access_token(),
                user_agent=self.config_manager.get_user_agent(),
                proxy=proxy_url,
            )
        except Exception as e:
            logger.error(f"服务初始化失败: {e}")

        # 2. 初始化业务逻辑服务 (Dependency Injection)
        self.subscription_service = None
        if self.storage and self.service:
            self.subscription_service = SubscriptionService(
                repository=self.storage,
                service=self.service,
                config_manager=self.config_manager,
            )

    async def initialize(self):
        """
        插件加载时自动运行的初始化方法。
        """
        # 获取插件数据目录
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path
        from .src.utils.env_manager import EnvManager

        data_dir = get_astrbot_data_path()
        self.env_manager = EnvManager(data_dir)

        # 检查本地渲染环境，但不强制安装（因为 RPC 是首选）
        if not self.env_manager.is_installed():
            logger.info(
                "本地 Playwright 环境未就绪，将优先使用 RPC 渲染（如果已配置）。"
            )

        # 添加定时任务
        if self.subscription_service:
            try:
                self.scheduler_manager.add_job(
                    func=self.subscription_service.check_updates,
                    trigger="cron",
                    minute=0,
                )
                logger.info("Bangumi 插件定时更新任务已启动")
            except Exception as e:
                logger.error(f"添加定时任务失败: {e}")

        logger.info("Bangumi 插件初始化流程结束")

    # --- 内部核心逻辑 ---

    async def _render_subjects(
        self, subjects: list, top_k: int = 1
    ) -> tuple[list[Comp.Image], list[str], list[str]]:
        """
        核心渲染逻辑：处理条目列表，获取详情并生成图片。
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
            if not subject_data:
                logger.warning(f"获取条目 {subject_id} 详情失败，跳过")
                continue

            # 获取剧集信息用于渲染 episode 进度
            try:
                episodes_data = await self.service.get_subject_episodes(subject_id)
                if episodes_data and "data" in episodes_data:
                    subject_data["episodes"] = episodes_data["data"]
            except Exception as e:
                logger.warning(f"获取条目 {subject_id} 剧集信息失败: {e}")

            data_list.append(subject_data)

            # 创建临时文件
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
            os.close(tmp_fd)  # 立即关闭文件描述符，只保留路径
            temp_files.append(tmp_path)

        # 创建渲染器实例
        renderer = SubjectRenderer()
        await renderer.render_batch_subject_cards(
            data_list=data_list,
            output_paths=temp_files,
            rpc_url=self.config_manager.get_render_server_url(),
            max_retries=self.config_manager.get_max_retries(),
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
        通用搜索处理逻辑：搜索 -> 渲染 -> 发送 -> 清理。
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
        """
        处理 Bangumi 每日放送的渲染和发送逻辑。
        """
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
            base64_image = await renderer.render_calendar(
                calendar_res,
                rpc_url=self.config_manager.get_render_server_url(),
                max_retries=self.config_manager.get_max_retries(),
            )

            # 3. 发送图片
            if base64_image:
                yield event.chain_result([Comp.Image.fromBase64(base64_image)])
            else:
                yield event.plain_result("❌ 图片生成失败")

        except Exception as e:
            logger.error(f"处理每日放送失败: {e}")
            yield event.plain_result(f"❌ 处理失败: {e}")

    # --- 命令处理区 ---

    @filter.command("bgm")
    async def search(
        self, event: AstrMessageEvent, query: str, top_k: int | None = None
    ):
        async for result in self._handle_subject(
            event, query, top_k, subject_type=None
        ):
            yield result

    @filter.command("bgm番剧")
    async def search_anime(
        self, event: AstrMessageEvent, query: str, top_k: int | None = None
    ):
        async for result in self._handle_subject(
            event, query, top_k, subject_type=[2], subject_tags=["TV"]
        ):
            yield result

    @filter.command("bgm剧场版")
    async def search_movie(
        self, event: AstrMessageEvent, query: str, top_k: int | None = None
    ):
        async for result in self._handle_subject(
            event, query, top_k, subject_type=[2], subject_tags=["剧场版"]
        ):
            yield result

    @filter.command("bgm漫画")
    async def search_manga(
        self, event: AstrMessageEvent, query: str, top_k: int | None = None
    ):
        async for result in self._handle_subject(
            event, query, top_k, subject_type=[1], subject_tags=["漫画"]
        ):
            yield result

    @filter.command("today")
    async def calendar(self, event: AstrMessageEvent):
        async for result in self._handle_calendar(event):
            yield result

    @filter.command("bgm_debug")
    async def bgm_debug(self, event: AstrMessageEvent):
        """
        调试指令：查看数据库状态。
        """
        if not self.storage:
            yield event.plain_result("Storage not initialized")
            return

        # 测试用：重置番剧 525565 的 current_episode 为 0
        self.storage.update_subject_episode("525565", 0)

        msg = [f"DB Path: {self.storage.db_path}"]
        if os.path.exists(self.storage.db_path):
            msg.append(
                f"File exists, size: {os.path.getsize(self.storage.db_path)} bytes"
            )

        # 查询数据
        try:
            from .src.db import BangumiSubject, Subscription

            session = self.storage.Session()
            subjects = session.query(BangumiSubject).all()
            msg.append(f"\nSubjects ({len(subjects)}):")
            for s in subjects:
                msg.append(str(s))
            session.close()
        except Exception as e:
            msg.append(f"\nError querying DB: {e}")

        # 设置10秒后触发一次更新检查
        if self.subscription_service:
            run_time = datetime.datetime.now() + datetime.timedelta(seconds=10)
            self.scheduler_manager.add_job(
                func=self.subscription_service.check_updates,
                trigger="date",
                run_date=run_time,
            )
            msg.append("\n⏰ 已设置10秒后触发一次更新检查任务")

        yield event.plain_result("\n".join(msg))

    @filter.command("追番")
    async def subscribe(self, event: AstrMessageEvent, query: str):
        if not self.subscription_service:
            yield event.plain_result("❌ 订阅服务未就绪")
            return

        group_id = getattr(event, "session_id", None)
        if hasattr(event, "message_obj") and hasattr(event.message_obj, "group_id"):
            group_id = event.message_obj.group_id

        if not group_id:
            yield event.plain_result("❌ 无法获取群组ID")
            return

        result = await self.subscription_service.subscribe(group_id, query)
        yield event.plain_result(result)

    @filter.command("弃坑")
    async def unsubscribe(self, event: AstrMessageEvent, query: str):
        if not self.subscription_service:
            yield event.plain_result("❌ 订阅服务未就绪")
            return

        group_id = getattr(event, "session_id", None)
        if hasattr(event, "message_obj") and hasattr(event.message_obj, "group_id"):
            group_id = event.message_obj.group_id

        if not group_id:
            yield event.plain_result("❌ 无法获取群组ID")
            return

        result = await self.subscription_service.unsubscribe(group_id, query)
        yield event.plain_result(result)

    async def terminate(self):
        logger.info("正在清理调度器...")
        if self.scheduler_manager.scheduler.running:
            self.scheduler_manager.scheduler.shutdown(wait=False)
        await super().terminate()
