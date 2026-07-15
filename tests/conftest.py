from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_bangumi.src.entities import Episode, Subject


@pytest.fixture
def subject() -> Subject:
    return Subject(
        id=454083,
        type=2,
        name="Sample Anime",
        name_cn="示例动画",
        summary="这是一段用于卡片和追番测试的条目简介。",
        air_date="2026-07-01",
        platform="TV",
        total_episodes=12,
        score=8.2,
        score_count=2345,
        rank=321,
        cover_url="https://example.com/cover.jpg",
        tags=("原创", "科幻", "日常"),
    )


@pytest.fixture
def episode() -> Episode:
    return Episode(
        id=1001,
        subject_id=454083,
        type=0,
        number=4,
        sort=4,
        name="Episode 4",
        name_cn="第四集",
        air_date="2026-07-14",
        summary="本集简介。",
        duration="00:24:00",
        comments=12,
    )


@pytest.fixture
def html_render() -> AsyncMock:
    return AsyncMock(return_value=str(Path("rendered.jpg").resolve()))


@pytest.fixture
def context() -> MagicMock:
    value = MagicMock()
    value.send_message = AsyncMock(return_value=True)
    value.get_using_provider.return_value = None
    platform = MagicMock()
    platform.meta.return_value = SimpleNamespace(
        id="onebot-main",
        name="aiocqhttp",
    )
    value.platform_manager.platform_insts = [platform]
    return value
