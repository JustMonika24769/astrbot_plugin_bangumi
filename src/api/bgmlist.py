"""
bgmlist.com API 客户端

提供获取热门番剧广播时间数据的功能。
数据来源: https://bgmlist.com (开源项目 wxt2005/bangumi-list-v3)
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping

import aiohttp
from astrbot.api import logger

from ..entities import BroadcastSchedule

BGM_LIST_API = "https://bgmlist.com/api/v1/bangumi/onair"


def _parse_broadcast_schedule(begin_iso: str) -> BroadcastSchedule | None:
    """
    从 bgmlist 的 begin 字段解析出 CST (UTC+8) 的首播日期和时间

    Args:
        begin_iso: ISO 格式的首次播出时间,如 "2026-04-06T14:00:00.000Z"

    Returns:
        CST 首播安排,解析失败返回 None
    """
    if not begin_iso:
        return None

    try:
        dt_str = begin_iso
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"

        dt = datetime.datetime.fromisoformat(dt_str)
        # 若为 naive datetime（无时区信息），按 UTC 处理
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.UTC)
        cst_offset = datetime.timedelta(hours=8)
        cst_dt = dt.astimezone(datetime.timezone(cst_offset))

        return BroadcastSchedule(
            broadcast_date=cst_dt.strftime("%Y-%m-%d"),
            broadcast_time=cst_dt.strftime("%H:%M"),
        )
    except (ValueError, TypeError) as e:
        logger.warning(f"解析广播时间失败: {begin_iso} - {e}")
        return None


def _parse_broadcast_time(begin_iso: str) -> str | None:
    """兼容旧调用方，仅返回 CST 时间。"""
    schedule = _parse_broadcast_schedule(begin_iso)
    return schedule.broadcast_time if schedule else None


async def fetch_onair_data(
    session: aiohttp.ClientSession | None = None,
    proxy_url: str | None = None,
) -> dict[str, BroadcastSchedule] | None:
    """
    从 bgmlist API 获取放送中番剧的播出时间数据

    Args:
        session: 可选的 aiohttp.ClientSession。若为 None 则创建临时 session。

    Returns:
        {bangumi_subject_id: BroadcastSchedule} 的映射
        失败返回 None
    """
    _session: aiohttp.ClientSession | None = session
    _close = session is None

    try:
        if _session is None:
            _session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15, connect=10),
                headers={
                    "User-Agent": "AstrBot-BangumiPlugin/2.0",
                    "Accept": "application/json",
                },
            )

        assert _session is not None  # mypy: narrow Optional after None check

        async with _session.get(
            BGM_LIST_API,
            timeout=aiohttp.ClientTimeout(total=15, connect=10),
            headers={
                "User-Agent": "AstrBot-BangumiPlugin/2.0",
                "Accept": "application/json",
            },
            proxy=proxy_url,
        ) as resp:
            if resp.status != 200:
                logger.warning(f"bgmlist API 返回 {resp.status}")
                return None
            data = await resp.json()

        items = data.get("items", []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            logger.warning("bgmlist API 返回格式异常: data 非列表")
            return None

        result: dict[str, BroadcastSchedule] = {}
        for item in items:
            if not isinstance(item, Mapping):
                continue

            # 查找 bangumi ID
            sites = item.get("sites", [])
            bangumi_id: str | None = None
            if isinstance(sites, list):
                for site in sites:
                    if isinstance(site, Mapping) and site.get("site") == "bangumi":
                        bangumi_id = str(site.get("id", ""))
                        break

            if not bangumi_id:
                continue

            # 解析播出时间
            begin_raw = item.get("begin")
            schedule = _parse_broadcast_schedule(
                str(begin_raw) if begin_raw else ""
            )
            if schedule:
                result[bangumi_id] = schedule

        logger.info(f"从 bgmlist 获取到 {len(result)} 条放送时间数据")
        return result

    except (aiohttp.ClientError, OSError, ValueError) as e:
        logger.warning(f"获取 bgmlist 数据失败: {e}")
        return None
    finally:
        if _close and _session is not None:
            await _session.close()
