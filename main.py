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


@register(
    "astrbot_plugin_bangumi",
    "Gemini",
    "一个用于查询Bangumi条目信息的插件",
    "1.2.0",
    "https://github.com/bangumi/api",
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
            logger.info("Bangumi插件初始化成功")
        except ValueError as e:
            logger.error(f"插件初始化失败: {e}")

    # --- 命令处理区 ---

    @filter.command("bgm搜索")
    async def accurate_search(
        self, event: AstrMessageEvent, query: str, top_k: int | None = None
    ):
        if not self.service:
            yield event.plain_result("❌ 配置未完成")
            return

        logger.info(f"top_k: {top_k}")

        if query is None:
            yield event.plain_result("❌ 用法: /bgm搜索 <关键词|ID>")
            return

        # 1. 搜索条目
        search_res = await self.service.search_subjects(query)
        if not search_res or "data" not in search_res or not search_res["data"]:
            yield event.plain_result("🔍 未找到相关条目")
            return

        # 2. 遍历结果并渲染
        image_components = []
        temp_files = []

        if top_k is None:
            top_k = 1
        try:
            top_k = int(top_k)
        except (ValueError, TypeError):
            top_k = 1

        try:
            logger.info(f"搜索结果: {len(search_res['data'])}")
            iterator = search_res["data"][:top_k]
            for item in iterator:
                subject_id = item["id"]

                # 获取详细信息
                subject_data = await self.service.get_subject_details(subject_id)
                if not subject_data:
                    logger.warning(f"获取条目 {subject_id} 详情失败，跳过")
                    continue

                # 渲染图片
                renderer = SubjectRenderer()

                # 创建临时文件
                tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
                os.close(tmp_fd)  # 立即关闭文件描述符，只保留路径
                temp_files.append(tmp_path)

                try:
                    await renderer.render_subject_card(
                        subject_data,
                        output_path=tmp_path,
                        max_retries=self.config_manager.get_max_retries(),
                    )

                    if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                        image_components.append(Comp.Image.fromFileSystem(tmp_path))
                    else:
                        logger.warning(f"图片生成失败: {subject_id}")
                except Exception as e:
                    logger.error(f"渲染条目 {subject_id} 失败: {e}")

            # 3. 发送图片
            if image_components:
                yield event.chain_result(image_components)
            else:
                yield event.plain_result("❌ 未能生成任何图片")

        except Exception as e:
            logger.error(f"批量处理失败: {e}")
            yield event.plain_result(f"❌ 处理失败: {e}")
        finally:
            # 清理临时文件
            await asyncio.sleep(1)  # 稍作等待确保发送完成
            for path in temp_files:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception as e:
                    logger.warning(f"清理临时文件失败 {path}: {e}")
