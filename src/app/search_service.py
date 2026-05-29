from __future__ import annotations

import datetime
import logging
from typing import cast

from ..domain.contracts import (
    CalendarDay,
    RenderData,
    SearchSubjectItem,
    SubjectDetailsResponse,
)
from ..domain.exceptions import BangumiApiError
from .ports import (
    BangumiApiPort,
    CalendarRendererPort,
    RenderConfigPort,
    SubjectRendererPort,
)
from .responses import AppImages, AppResponse, AppText

logger = logging.getLogger(__name__)


class SearchService:
    def __init__(
        self,
        bangumi_api: BangumiApiPort,
        render_config: RenderConfigPort,
        subject_renderer: SubjectRendererPort,
        calendar_renderer: CalendarRendererPort,
    ) -> None:
        self.bangumi_api = bangumi_api
        self.render_config = render_config
        self.subject_renderer = subject_renderer
        self.calendar_renderer = calendar_renderer

    async def handle_subject_search(
        self,
        query: str,
        top_k: int = 1,
        subject_type: list[int] | None = None,
        subject_tags: list[str] | None = None,
    ) -> AppResponse:
        """
        处理条目搜索的核心流程:搜索 -> 渲染 (Base64) -> 返回应用响应
        """
        if not query:
            return AppText("❌ 请提供搜索关键词")

        logger.info("搜索请求: %s, type=%s, top_k=%s", query, subject_type, top_k)

        try:
            search_res = await self.bangumi_api.search_subjects(
                keyword=query, subject_type=subject_type, subject_tags=subject_tags
            )
            if not search_res.get("data"):
                return AppText("🔍 未找到相关条目")

            base64_images = await self._prepare_subject_images_base64(
                search_res["data"], top_k
            )

            if base64_images:
                return AppImages.from_iterable(base64_images)
            return AppText("❌ 未能生成渲染图片")

        except (BangumiApiError, RuntimeError, ValueError) as e:
            logger.error("SearchService.handle_subject_search 失败: %s", e)
            return AppText(f"❌ 处理失败: {e}")

    async def handle_calendar(self) -> AppResponse:
        """
        处理每日放送逻辑
        """
        try:
            calendar_res = await self.bangumi_api.get_calendar()
            if not calendar_res:
                return AppText("❌ 未获取到放送数据")

            base64_image = await self.calendar_renderer.render_calendar(
                calendar_res,
                rpc_url=self.render_config.get_render_server_url(),
                max_retries=self.render_config.get_max_retries(),
            )

            if base64_image:
                return AppImages.single(base64_image)
            return AppText("❌ 图片生成失败")
        except (BangumiApiError, RuntimeError, ValueError) as e:
            logger.error("SearchService.handle_calendar 失败: %s", e)
            return AppText(f"❌ 处理失败: {e}")

    async def handle_today(self) -> AppResponse:
        """
        处理今日放送逻辑
        """
        try:
            calendar_res = await self.bangumi_api.get_calendar()
            if not calendar_res:
                return AppText("❌ 未获取到今日放送数据")

            today_data = self._filter_today_calendar(calendar_res)
            if not today_data:
                return AppText("❌ 未获取到今日放送数据")

            base64_image = await self.calendar_renderer.render_calendar(
                today_data,
                rpc_url=self.render_config.get_render_server_url(),
                max_retries=self.render_config.get_max_retries(),
            )

            if base64_image:
                return AppImages.single(base64_image)
            return AppText("❌ 图片生成失败")
        except (BangumiApiError, RuntimeError, ValueError) as e:
            logger.error("SearchService.handle_today 失败: %s", e)
            return AppText(f"❌ 处理失败: {e}")

    @staticmethod
    def _filter_today_calendar(calendar_data: list[CalendarDay]) -> list[CalendarDay]:
        today_id = datetime.datetime.now().isoweekday()
        for day in calendar_data:
            weekday = day.get("weekday", {})
            if weekday.get("id") == today_id:
                today = day.copy()
                today["is_today"] = True
                return [today]
        return []

    async def _prepare_subject_images_base64(
        self, subjects: list[SearchSubjectItem], top_k: int
    ) -> list[str]:
        """
        内部逻辑:准备渲染数据并生成 Base64 图片
        """
        data_list: list[SubjectDetailsResponse] = []

        for item in subjects[:top_k]:
            subject_id = item.get("id")
            if not subject_id:
                continue

            subject_data = await self.bangumi_api.get_subject_details(str(subject_id))
            if not subject_data:
                continue

            subject_payload = subject_data.copy()
            try:
                episodes_data = await self.bangumi_api.get_subject_episodes(
                    int(subject_id)
                )
                if episodes_data.get("data"):
                    subject_payload["episodes"] = episodes_data["data"]
            except (BangumiApiError, ValueError, TypeError) as e:
                logger.warning("获取剧集信息失败 (subject_id=%s): %s", subject_id, e)

            data_list.append(subject_payload)

        if not data_list:
            return []

        return await self.subject_renderer.render_batch_subject_cards_to_base64(
            data_list=cast(list[RenderData], data_list),
            rpc_url=self.render_config.get_render_server_url(),
            max_retries=self.render_config.get_max_retries(),
        )
