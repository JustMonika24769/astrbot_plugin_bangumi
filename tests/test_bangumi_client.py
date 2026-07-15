from __future__ import annotations

import base64
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_bangumi.src import bangumi_client as client_module
from astrbot_plugin_bangumi.src.bangumi_client import BangumiClient


def build_client() -> BangumiClient:
    return BangumiClient(
        MagicMock(),
        access_token="",
        user_agent="test",
        proxy_url=None,
        timeout_seconds=10,
        max_retries=2,
    )


@pytest.mark.asyncio
async def test_numeric_search_uses_subject_details() -> None:
    client = build_client()
    client.get_subject = AsyncMock(
        return_value=client._parse_subject(
            {"id": 454083, "type": 2, "name_cn": "示例动画"}
        )
    )

    result = await client.search_subjects("454083", subject_types=(2,))

    assert [subject.id for subject in result] == [454083]
    client.get_subject.assert_awaited_once_with(454083)


def test_client_rejects_empty_user_agent_at_the_http_boundary() -> None:
    client = BangumiClient(
        MagicMock(),
        access_token="",
        user_agent="   ",
        proxy_url=None,
        timeout_seconds=10,
        max_retries=2,
    )

    assert client.headers["User-Agent"].startswith("AstrBot-Bangumi-Plugin/")


@pytest.mark.asyncio
async def test_keyword_search_passes_structured_filters() -> None:
    client = build_client()
    client._request = AsyncMock(
        return_value={
            "data": [
                {
                    "id": 1,
                    "type": 2,
                    "name": "A",
                    "rating": {"score": 8.1, "total": 20},
                }
            ]
        }
    )

    result = await client.search_subjects(
        "A", limit=3, subject_types=(2,), tags=("TV",)
    )

    assert result[0].score == 8.1
    payload = client._request.await_args.kwargs["json_data"]
    assert payload["filter"] == {"type": [2], "tag": ["TV"]}
    assert payload["limit"] == 3


@pytest.mark.asyncio
async def test_cover_is_embedded_as_data_uri() -> None:
    client = build_client()
    client._request_bytes = AsyncMock(return_value=(b"image", "image/jpeg"))
    subject = client._parse_subject({"id": 1, "type": 2, "name": "A"})

    embedded = await client.with_embedded_cover(subject)

    assert embedded.cover_url == (
        "data:image/jpeg;base64," + base64.b64encode(b"image").decode("ascii")
    )


@pytest.mark.asyncio
async def test_episode_api_is_paginated() -> None:
    client = build_client()
    first_page = {
        "total": 101,
        "data": [
            {
                "id": index,
                "subject_id": 1,
                "type": 0,
                "ep": index,
                "sort": index,
            }
            for index in range(1, 101)
        ],
    }
    second_page = {
        "total": 101,
        "data": [{"id": 101, "subject_id": 1, "type": 0, "ep": 101, "sort": 101}],
    }
    client._request = AsyncMock(side_effect=[first_page, second_page])

    episodes = await client.get_episodes(1)

    assert len(episodes) == 101
    assert client._request.await_count == 2
    assert client._request.await_args_list[1].kwargs["params"]["offset"] == 100


@pytest.mark.asyncio
async def test_latest_episode_uses_date_without_requiring_comments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = build_client()
    client.get_episodes = AsyncMock(
        return_value=[
            client._parse_episode(
                {
                    "id": 1,
                    "subject_id": 1,
                    "type": 0,
                    "ep": 1,
                    "sort": 1,
                    "airdate": "2026-07-13",
                    "comment": 0,
                }
            ),
            client._parse_episode(
                {
                    "id": 2,
                    "subject_id": 1,
                    "type": 1,
                    "ep": 2,
                    "sort": 2,
                    "airdate": "2026-07-14",
                    "comment": 20,
                }
            ),
        ]
    )
    monkeypatch.setattr(
        client_module,
        "datetime",
        _fixed_datetime(2026, 7, 14, 12, 0),
    )

    latest = await client.get_latest_aired_episode(1)

    assert latest is not None
    assert latest.number == 1


@pytest.mark.asyncio
async def test_latest_episode_respects_broadcast_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = build_client()
    client.get_episodes = AsyncMock(
        return_value=[
            client._parse_episode(
                {
                    "id": 1,
                    "subject_id": 1,
                    "type": 0,
                    "ep": 1,
                    "sort": 1,
                    "airdate": "2026-07-13",
                }
            ),
            client._parse_episode(
                {
                    "id": 2,
                    "subject_id": 1,
                    "type": 0,
                    "ep": 2,
                    "sort": 2,
                    "airdate": "2026-07-14",
                }
            ),
        ]
    )
    monkeypatch.setattr(
        client_module,
        "datetime",
        _fixed_datetime(2026, 7, 14, 21, 59),
    )

    latest = await client.get_latest_aired_episode(1, broadcast_time="22:00")

    assert latest is not None
    assert latest.number == 1


@pytest.mark.asyncio
async def test_latest_episode_waits_for_same_day_activity_without_broadcast_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = build_client()
    client.get_episodes = AsyncMock(
        return_value=[
            client._parse_episode(
                {
                    "id": 1,
                    "subject_id": 1,
                    "type": 0,
                    "ep": 1,
                    "sort": 1,
                    "airdate": "2026-07-13",
                }
            ),
            client._parse_episode(
                {
                    "id": 2,
                    "subject_id": 1,
                    "type": 0,
                    "ep": 2,
                    "sort": 2,
                    "airdate": "2026-07-14",
                    "comment": 0,
                }
            ),
        ]
    )
    monkeypatch.setattr(
        client_module,
        "datetime",
        _fixed_datetime(2026, 7, 14, 21, 59),
    )

    latest = await client.get_latest_aired_episode(1)

    assert latest is not None
    assert latest.number == 1


def _fixed_datetime(year: int, month: int, day: int, hour: int, minute: int):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(year, month, day, hour, minute, tzinfo=tz)

    return FixedDateTime
