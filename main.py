import os
import datetime
import aiohttp

from astrbot.api import logger
from astrbot.api.all import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

# 导入配置与管理
from .src.config.config_manager import ConfigManager
from .src.utils.scheduler import SchedulerManager
from astrbot.api.star import StarTools
# 导入逻辑服务
from .src.services import BangumiService
from .src.services.subscription import SubscriptionService
from .src.services.search import SearchService
from .src.db import BangumiRepository


@register(
    "astrbot_plugin_bangumi_enhance",
    "united_pooh",
    "一个用于查询Bangumi条目信息的插件",
    "1.0.0",
    "https://github.com/united-pooh/astrbot_plugin_bangumi",
)
class BangumiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        """
        初始化 BangumiPlugin 插件。
        """
        super().__init__(context)
        self.config = config
        self.config_manager = ConfigManager(config)
        self.scheduler_manager = SchedulerManager()

        self.session = None
        self.storage = None
        self.service = None
        self.subscription_service = None
        self.search_service = None

    async def initialize(self) -> None:
        """
        插件加载时自动运行的初始化方法。
        """
        # 1. 初始化数据库
        try:
            self.storage = BangumiRepository()
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")

        # 2. 初始化网络会话 (Shared Session)
        self.session = aiohttp.ClientSession()

        # 3. 初始化核心 API 服务
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
                session=self.session,
            )
        except Exception as e:
            logger.error(f"服务初始化失败: {e}")

        # 4. 初始化业务逻辑服务 (Dependency Injection)
        if self.service:
            # 搜索服务
            self.search_service = SearchService(
                service=self.service,
                config_manager=self.config_manager,
                session=self.session
            )

            # 订阅服务
            if self.storage:
                self.subscription_service = SubscriptionService(
                    repository=self.storage,
                    service=self.service,
                    config_manager=self.config_manager,
                    session=self.session
                )

        # 5. 其他初始化流程
        from astrbot.api.star import StarTools
        from .src.utils.env_manager import EnvManager

        plugin_data_dir = StarTools.get_data_dir()
        self.env_manager = EnvManager(plugin_data_dir)

        # 检查本地渲染环境
        if not self.env_manager.is_installed():
            logger.info(
                "本地 Playwright 环境未就绪，将优先使用 RPC 渲染（如果已配置）。"
            )

        # 添加定时更新任务
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

    # --- 命令处理区 ---

    @filter.command("bgm")
    async def search(self, event: AstrMessageEvent, query: str, top_k: int = 1):
        if not self.search_service:
            yield event.plain_result("❌ 搜索服务未就绪")
            return
        async for result in self.search_service.handle_subject_search(
            event, query, top_k, subject_type=None
        ):
            yield result

    @filter.command("bgm番剧")
    async def search_anime(self, event: AstrMessageEvent, query: str, top_k: int = 1):
        if not self.search_service:
            yield event.plain_result("❌ 搜索服务未就绪")
            return
        async for result in self.search_service.handle_subject_search(
            event, query, top_k, subject_type=[2], subject_tags=["TV"]
        ):
            yield result

    @filter.command("bgm剧场版")
    async def search_movie(self, event: AstrMessageEvent, query: str, top_k: int = 1):
        if not self.search_service:
            yield event.plain_result("❌ 搜索服务未就绪")
            return
        async for result in self.search_service.handle_subject_search(
            event, query, top_k, subject_type=[2], subject_tags=["剧场版"]
        ):
            yield result

    @filter.command("bgm漫画")
    async def search_manga(self, event: AstrMessageEvent, query: str, top_k: int = 1):
        if not self.search_service:
            yield event.plain_result("❌ 搜索服务未就绪")
            return
        async for result in self.search_service.handle_subject_search(
            event, query, top_k, subject_type=[1], subject_tags=["漫画"]
        ):
            yield result

    @filter.command("today")
    async def calendar(self, event: AstrMessageEvent):
        if not self.search_service:
            yield event.plain_result("❌ 搜索服务未就绪")
            return
        async for result in self.search_service.handle_calendar(event):
            yield result

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
        logger.info("正在清理 Bangumi 插件资源...")
        if self.scheduler_manager.scheduler.running:
            self.scheduler_manager.scheduler.shutdown(wait=False)

        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("已关闭共享网络会话")

        await super().terminate()
