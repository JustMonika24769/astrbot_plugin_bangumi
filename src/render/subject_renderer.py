import datetime
import asyncio
from collections import Counter
from typing import cast

from astrbot.api import logger
from .base_renderer import BaseRenderer
from ..services import EpisodeItem, RenderData, SubjectType

# --- 数据处理工具函数 (高度解耦模块) ---


def _process_images(data: RenderData) -> None:
    """
    处理图片 URL 的提取
    """
    if "image_url" in data:
        return

    images = data.get("images")
    if not isinstance(images, dict):
        return

    images = cast(dict[str, object], images)
    data["image_url"] = (
        images.get("large") or images.get("common") or images.get("medium") or ""
    )


def _process_dates(data: RenderData) -> None:
    """
    处理日期字段
    """
    if "date" in data:
        return

    if "air_date" in data:
        data["date"] = data["air_date"]


def _process_platform(data: RenderData) -> None:
    """
    处理平台/类型映射
    """
    if "platform" in data:
        return

    if "type" not in data:
        return

    try:
        type_id = int(data["type"])
        data["platform"] = SubjectType(type_id).to_display()
    except (ValueError, TypeError):
        data["platform"] = "未知"


def _infer_air_weekday(aired_weekdays: list[int]) -> str:
    """
    从已播出的剧集中推断主要放送星期
    """
    if not aired_weekdays:
        return ""

    weekday_names = {1: "月", 2: "火", 3: "水", 4: "木", 5: "金", 6: "土", 7: "日"}
    # 取最近 4 集的星期，避免早期特殊排期干扰
    recent = aired_weekdays[-4:]
    most_common = Counter(recent).most_common(1)[0][0]
    return weekday_names.get(most_common, "")


def _parse_episode_list(
    episodes: list[EpisodeItem], today: datetime.date
) -> tuple[list[dict[str, int | bool | None]], list[int]]:
    """
    解析剧集列表，返回 (渲染用列表, 已播出星期列表)
    """
    episode_list: list[dict[str, int | bool | None]] = []
    aired_weekdays: list[int] = []

    for ep in episodes:
        if ep.get("type", 0) != 0 or ep.get("ep", 0) == 0:
            continue

        aired = False
        airdate_str = ep.get("airdate")

        if airdate_str:
            try:
                airdate = datetime.datetime.strptime(airdate_str, "%Y-%m-%d").date()
                aired = airdate <= today
                if aired:
                    aired_weekdays.append(airdate.isoweekday())
            except ValueError:
                pass

        # 补充逻辑：有评论也视为已播出
        if ep.get("comment", 0) > 0:
            aired = True

        episode_list.append({"ep": ep.get("ep"), "aired": aired})

    return episode_list, aired_weekdays


def _process_episodes(data: RenderData) -> None:
    """
    处理剧集状态和更新日推算的主流程
    """
    episodes = data.get("episodes")
    if not isinstance(episodes, list):
        return

    today = datetime.date.today()

    # 1. 解析剧集数据
    normalized_episodes: list[EpisodeItem] = []
    for episode in episodes:
        if isinstance(episode, dict):
            normalized_episodes.append(cast(EpisodeItem, episode))
    episode_list, aired_weekdays = _parse_episode_list(normalized_episodes, today)
    data["episode_list"] = episode_list

    # 2. 推算放送星期
    air_weekday = _infer_air_weekday(aired_weekdays)
    if air_weekday:
        data["air_weekday"] = air_weekday


def preprocess_data(data: RenderData) -> RenderData:
    """
    预处理数据以适配模板
    """
    processed = data.copy()

    _process_images(processed)
    _process_dates(processed)
    _process_platform(processed)
    _process_episodes(processed)

    return processed


class SubjectRenderer(BaseRenderer):
    async def render_subject_card(
        self,
        data: RenderData,
        rpc_url: str | None = None,
        headless: bool = True,
        wait_time: int = 0,
        max_retries: int = 3,
        timeout: int = 30000,
    ) -> str | None:
        """
        渲染条目卡片并返回 Base64 字符串
        """
        render_data = preprocess_data(data)
        response_data = await self.render(
            template_path="subject/subject.html",
            render_data=render_data,
            selector="#card",
            sub_dir="subject",
            rpc_url=rpc_url,
            headless=headless,
            max_retries=max_retries,
            wait_time=wait_time,
            timeout=timeout,
        )
        return response_data

    async def render_batch_subject_cards_to_base64(
        self,
        data_list: list[RenderData],
        rpc_url: str | None = None,
        headless: bool = True,
        wait_time: int = 0,
        max_retries: int = 3,
        timeout: int = 30000,
        max_concurrency: int = 3,
    ) -> list[str]:
        """
        批量渲染条目卡片并直接返回 Base64 字符串列表。

        Args:
            max_concurrency: 最大并发渲染数，防止压垮浏览器/RPC 服务
        """
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _limited_render(data: RenderData) -> str | None:
            async with semaphore:
                return await self.render_subject_card(
                    data=data,
                    rpc_url=rpc_url,
                    headless=headless,
                    wait_time=wait_time,
                    max_retries=max_retries,
                    timeout=timeout,
                )

        tasks = [_limited_render(data) for data in data_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_results: list[str] = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.warning(f"批量渲染第 {i + 1} 项失败: {res}")
            elif res:
                valid_results.append(res)
        return valid_results
