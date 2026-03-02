import asyncio
import os
import tempfile
from typing import List, Optional, Tuple, Any, AsyncGenerator

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from .base import BangumiService
from ..config.config_manager import ConfigManager
from ..render.subject_renderer import SubjectRenderer
from ..render.calendar_renderer import CalendarRenderer

class SearchService:
    def __init__(self, service: BangumiService, config_manager: ConfigManager):
        self.service = service
        self.config_manager = config_manager
        self.subject_renderer = SubjectRenderer()
        self.calendar_renderer = CalendarRenderer()

    async def handle_subject_search(
        self,
        event: AstrMessageEvent,
        query: str,
        top_k: int = 1,
        subject_type: Optional[List[int]] = None,
        subject_tags: Optional[List[str]] = None,
    ) -> AsyncGenerator[Any, None]:
        """
        处理条目搜索的核心流程：搜索 -> 渲染 -> 封装 -> 清理。
        """
        if not query:
            yield event.plain_result("❌ 请提供搜索关键词")
            return

        logger.info(f"搜索请求: {query}, type={subject_type}, top_k={top_k}")

        try:
            # 1. 搜索条目
            search_res = await self.service.search_subjects(
                keyword=query, subject_type=subject_type, subject_tags=subject_tags
            )
            if not search_res or "data" not in search_res or not search_res["data"]:
                yield event.plain_result("🔍 未找到相关条目")
                return

            # 2. 渲染并获取组件
            image_components, temp_files = await self._prepare_subject_images(search_res["data"], top_k)

            # 3. 发送结果
            if image_components:
                yield event.chain_result(image_components)
            else:
                yield event.plain_result("❌ 未能生成渲染图片")

            # 4. 清理临时文件 (异步延迟清理，确保图片已发送)
            if temp_files:
                await asyncio.sleep(2)
                for path in temp_files:
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                    except Exception as e:
                        logger.warning(f"清理临时文件失败 {path}: {e}")

        except Exception as e:
            logger.error(f"SearchService.handle_subject_search 失败: {e}")
            yield event.plain_result(f"❌ 处理失败: {e}")

    async def handle_calendar(self, event: AstrMessageEvent) -> AsyncGenerator[Any, None]:
        """
        处理每日放送逻辑。
        """
        try:
            calendar_res = await self.service.get_calendar()
            if not calendar_res:
                yield event.plain_result("❌ 未获取到放送数据")
                return

            base64_image = await self.calendar_renderer.render_calendar(
                calendar_res,
                rpc_url=self.config_manager.get_render_server_url(),
                max_retries=self.config_manager.get_max_retries(),
            )

            if base64_image:
                yield event.chain_result([Comp.Image.fromBase64(base64_image)])
            else:
                yield event.plain_result("❌ 图片生成失败")
        except Exception as e:
            logger.error(f"SearchService.handle_calendar 失败: {e}")
            yield event.plain_result(f"❌ 处理失败: {e}")

    async def _prepare_subject_images(self, subjects: list, top_k: int) -> Tuple[List[Comp.Image], List[str]]:
        """
        内部逻辑：准备渲染数据并生成图片。
        """
        data_list = []
        temp_files = []
        
        for item in subjects[:top_k]:
            subject_id = item.get("id") if isinstance(item, dict) else None
            if not subject_id:
                continue

            # 获取详情
            subject_data = await self.service.get_subject_details(subject_id)
            if not subject_data:
                continue

            # 补充剧集进度信息
            try:
                episodes_data = await self.service.get_subject_episodes(subject_id)
                if episodes_data and "data" in episodes_data:
                    subject_data["episodes"] = episodes_data["data"]
            except Exception:
                pass

            data_list.append(subject_data)
            
            # 创建临时占位文件
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
            os.close(tmp_fd)
            temp_files.append(tmp_path)

        if not data_list:
            return [], []

        # 批量渲染
        await self.subject_renderer.render_batch_subject_cards(
            data_list=data_list,
            output_paths=temp_files,
            rpc_url=self.config_manager.get_render_server_url(),
            max_retries=self.config_manager.get_max_retries(),
        )

        # 包装成消息组件
        image_components = []
        for path in temp_files:
            if os.path.exists(path) and os.path.getsize(path) > 0:
                image_components.append(Comp.Image.fromFileSystem(path))
        
        return image_components, temp_files
