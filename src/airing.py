from __future__ import annotations

from datetime import date, timedelta

from .entities import WEEKDAY_NAMES, Episode, parse_iso_date


def weekly_schedule(broadcast_date: str | None, broadcast_time: str | None) -> str:
    premiere = parse_iso_date(broadcast_date or "")
    clock = (broadcast_time or "").strip()
    if premiere:
        return f"常规每周{WEEKDAY_NAMES[premiere.weekday()]} {clock or '时间待定'}（北京时间）"
    if clock:
        return f"{clock}（北京时间）· 星期待定"
    return "常规放送时间待定"


def episode_schedule(episodes: list[Episode], today: date) -> dict[str, object]:
    """Describe recorded dates, without inferring hiatuses or an actual airing."""
    normal = [episode for episode in episodes if episode.type == 0]
    dated = [
        (episode, parsed)
        for episode in normal
        if (parsed := parse_iso_date(episode.air_date)) is not None
    ]
    upcoming = sorted(
        [(episode, day) for episode, day in dated if day >= today],
        key=lambda item: (item[1], item[0].sort, item[0].id),
    )
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    this_week = [(episode, day) for episode, day in dated if monday <= day <= sunday]
    if this_week:
        message = "本周有已收录放送日期；临时停更或延期可能尚未同步。"
    elif upcoming:
        message = "本周暂无已收录排期，可能停更、延期或资料未补全；请以官方公告为准。"
    else:
        message = "暂无后续已收录排期，可能已完结、停更或资料未补全；请以官方公告为准。"
    return {
        "message": message,
        "this_week": [episode.id for episode, _ in this_week],
        "upcoming": [episode.id for episode, _ in upcoming],
        "checked_date": today.isoformat(),
    }
