import datetime
from typing import cast

from astrbot.api import logger

from ..services import CalendarDay, CalendarWeekday, RenderData
from .base_renderer import BaseRenderer


def reorder_days(calendar_data: list[CalendarDay]) -> list[CalendarDay]:
    """
    重新排序天数,使今天排在第一位
    """
    today_id = datetime.datetime.now().isoweekday()

    today_index = 0
    for i, day in enumerate(calendar_data):
        weekday: CalendarWeekday = day.get("weekday", {})
        if weekday.get("id") == today_id:
            today_index = i
            day["is_today"] = True
            break

    reordered = calendar_data[today_index:] + calendar_data[:today_index]
    return reordered


class CalendarRenderer(BaseRenderer):
    async def render_calendar(
        self,
        calendar_data: list[CalendarDay],
        rpc_url: str | None = None,
        headless: bool = True,
        max_retries: int = 3,
    ) -> str | None:
        """
        渲染放送表图片并返回 Base64 字符串
        """
        try:
            reordered_days = reorder_days(calendar_data)
        except (ValueError, TypeError, RuntimeError) as e:
            logger.error(f"[-] 处理日历数据失败: {e}")
            return None

        return await self.render(
            template_path="calendar/calendar.html",
            render_data=cast(RenderData, {"days": reordered_days}),
            selector=".container",
            sub_dir="calendar",
            rpc_url=rpc_url,
            headless=headless,
            max_retries=max_retries,
            timeout=30000,
            wait_time=2,
        )
