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
                proxy=proxy_url
            )
            logger.info("Bangumi插件初始化成功")
        except ValueError as e:
            logger.error(f"插件初始化失败: {e}")

    # --- 命令处理区 ---

    @filter.command("bgm搜索")
    async def accurate_search(self, event: AstrMessageEvent):

        if not self.service:
            yield event.plain_result("❌ 配置未完成")
            return

        query = (
            event.message_str.split(maxsplit=1)[1].strip()
            if len(event.message_str.split()) > 1
            else ""
        )
        if not query:
            yield event.plain_result("❌ 用法: /bgm搜索 <关键词|ID>")
            return

        # 1. 搜索条目
        search_res = await self.service.search_subjects(query, limit=1)
        if not search_res or "data" not in search_res or not search_res["data"]:
            yield event.plain_result("🔍 未找到相关条目")
            return
        
        subject_id = search_res["data"][0]["id"]

        # 2. 获取详细信息 (为了更全的数据，如 tags, collection 等)
        subject_data = await self.service.get_subject_details(subject_id)
        if not subject_data:
            yield event.plain_result("❌ 获取条目详情失败")
            return

        # 3. 渲染图片并保存到临时文件
        renderer = SubjectRenderer()
        
        # 使用 tempfile 创建临时文件
        # delete=False 确保文件在关闭后不会立即被删除，以便发送
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
            tmp_path = tmp_file.name

        try:
            # 渲染图片
            await renderer.render_subject_card(subject_data, output_path=tmp_path, max_retries=self.config_manager.get_max_retries())
            
            # 4. 发送图片
            if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                yield event.chain_result([
                    Comp.Image.fromFileSystem(tmp_path)
                ])
            else:
                yield event.plain_result("❌ 图片生成失败")
                
        except Exception as e:
            logger.error(f"渲染或发送失败: {e}")
            yield event.plain_result(f"❌ 处理失败: {e}")
        finally:
            await asyncio.sleep(0.1)
            os.remove(tmp_path)
