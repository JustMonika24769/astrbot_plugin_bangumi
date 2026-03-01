import datetime
from typing import Any, Dict, List, Optional
from astrbot.api import logger
from .base_renderer import BaseRenderer


def reorder_days(calendar_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    重新排序天数，使今天排在第一位。
    """
    today_id = datetime.datetime.now().isoweekday()

    today_index = 0
    for i, day in enumerate(calendar_data):
        if day.get("weekday", {}).get("id") == today_id:
            today_index = i
            day["is_today"] = True
            break

    reordered = calendar_data[today_index:] + calendar_data[:today_index]
    return reordered


class CalendarRenderer(BaseRenderer):
    async def render_calendar(
        self,
        calendar_data: List[Dict[str, Any]],
        headless: bool = True,
        max_retries: int = 3,
    ) -> Optional[str]:
        """
        渲染放送表图片并返回 Base64 字符串。
        """
        try:
            reordered_days = reorder_days(calendar_data)
        except Exception as e:
            logger.error(f"处理日历数据失败: {e}")
            return None

        return await self._render_to_base64(
            template_path="calendar/calendar.html",
            render_data={"days": reordered_days},
            selector=".container",
            sub_dir="calendar",
            headless=headless,
            max_retries=max_retries,
            timeout=30000,
            wait_time=2,
        )
