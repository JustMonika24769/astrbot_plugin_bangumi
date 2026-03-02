import datetime
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from astrbot.api import logger
from .base_renderer import BaseRenderer
from ..services.types import SubjectType

# --- 数据处理工具函数 (高度解耦模块) ---


def _process_images(data: Dict[str, Any]) -> None:
    """
    处理图片 URL 的提取
    """
    if "image_url" in data:
        return

    images = data.get("images")
    if not images:
        return

    data["image_url"] = (
        images.get("large") or images.get("common") or images.get("medium") or ""
    )


def _process_dates(data: Dict[str, Any]) -> None:
    """
    处理日期字段
    """
    if "date" in data:
        return

    if "air_date" in data:
        data["date"] = data["air_date"]


def _process_platform(data: Dict[str, Any]) -> None:
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


def _infer_air_weekday(aired_weekdays: List[int]) -> str:
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
    episodes: List[Dict[str, Any]], today: datetime.date
) -> Tuple[List[Dict[str, Any]], List[int]]:
    """
    解析剧集列表，返回 (渲染用列表, 已播出星期列表)
    """
    episode_list = []
    aired_weekdays = []

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


def _process_episodes(data: Dict[str, Any]) -> None:
    """
    处理剧集状态和更新日推算的主流程
    """
    episodes = data.get("episodes")
    if not episodes:
        return

    today = datetime.date.today()

    # 1. 解析剧集数据
    episode_list, aired_weekdays = _parse_episode_list(episodes, today)
    data["episode_list"] = episode_list

    # 2. 推算放送星期
    air_weekday = _infer_air_weekday(aired_weekdays)
    if air_weekday:
        data["air_weekday"] = air_weekday


def preprocess_data(data: Dict[str, Any]) -> Dict[str, Any]:
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
        data: Dict[str, Any],
        rpc_url: Optional[str] = None,
        headless: bool = True,
        wait_time: int = 0,
        max_retries: int = 3,
        timeout: int = 30000,
    ) -> Optional[str]|None:
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


    async def render_batch_subject_cards(
        self,
        data_list: List[Dict[str, Any]],
        output_paths: List[str],
        rpc_url: Optional[str] = None,
        headless: bool = True,
        wait_time: int = 0,
        max_retries: int = 3,
    ) -> None:
        """
        批量渲染条目卡片并保存到文件。
        """
        if len(data_list) != len(output_paths):
            logger.error("数据列表和输出路径列表长度不一致")
            return

        import base64

        for data, path in zip(data_list, output_paths):
            base64_image = await self.render_subject_card(
                data=data,
                rpc_url=rpc_url,
                headless=headless,
                wait_time=wait_time,
                max_retries=max_retries,
            )
            if base64_image:
                try:
                    with open(path, "wb") as f:
                        f.write(base64.b64decode(base64_image))
                except Exception as e:
                    logger.error(f"保存图片到 {path} 失败: {e}")
            else:
                logger.error(f"渲染条目失败，跳过保存到 {path}")
