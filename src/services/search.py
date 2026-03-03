import asyncio
import os
import aiohttp
from typing import List, Optional, Tuple, Any, AsyncGenerator

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ..services import BangumiService
from ..config.config_manager import ConfigManager
from ..render.subject_renderer import SubjectRenderer
from ..render.calendar_renderer import CalendarRenderer


class SearchService:
    def __init__(
        self,
        service: BangumiService,
        config_manager: ConfigManager,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        self.service = service
        self.config_manager = config_manager
        self.subject_renderer = SubjectRenderer(session=session)
        self.calendar_renderer = CalendarRenderer(session=session)

    async def handle_subject_search(
        self,
        event: AstrMessageEvent,
        query: str,
        top_k: int = 1,
        subject_type: Optional[List[int]] = None,
        subject_tags: Optional[List[str]] = None,
    ) -> AsyncGenerator[Any, None]:
        """
        处理条目搜索的核心流程：搜索 -> 渲染 (Base64) -> 发送。
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

            # 2. 渲染并获取 Base64 组件
            image_components = await self._prepare_subject_images_base64(
                search_res["data"], top_k
            )

            # 3. 发送结果
            if image_components:
                yield event.chain_result(image_components)
            else:
                yield event.plain_result("❌ 未能生成渲染图片")

        except Exception as e:
            logger.error(f"SearchService.handle_subject_search 失败: {e}")
            yield event.plain_result(f"❌ 处理失败: {e}")

    async def handle_calendar(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[Any, None]:
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

    async def _prepare_subject_images_base64(
        self, subjects: list, top_k: int
    ) -> List[Comp.Image]:
        """
        内部逻辑：准备渲染数据并生成 Base64 图片组件。
        """
        data_list = []

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

        if not data_list:
            return []

        # 批量渲染为 Base64
        base64_list = await self.subject_renderer.render_batch_subject_cards_to_base64(
            data_list=data_list,
            rpc_url=self.config_manager.get_render_server_url(),
            max_retries=self.config_manager.get_max_retries(),
        )

        # 包装成消息组件
        return [Comp.Image.fromBase64(b64) for b64 in base64_list]
