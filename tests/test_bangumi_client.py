from __future__ import annotations

import asyncio
import base64
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_bangumi.src import bangumi_client as client_module
from astrbot_plugin_bangumi.src.bangumi_client import BangumiClient

PNG_IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII="
)


def build_client(cover_cache_dir: Path | None = None) -> BangumiClient:
    return BangumiClient(
        MagicMock(),
        access_token="",
        user_agent="test",
        proxy_url=None,
        timeout_seconds=10,
        max_retries=2,
        cover_cache_dir=cover_cache_dir,
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
    assert client._request.await_args.kwargs["params"] == {"limit": 3, "offset": 0}


@pytest.mark.asyncio
async def test_cover_is_embedded_as_data_uri() -> None:
    client = build_client()
    client._request_bytes = AsyncMock(return_value=(PNG_IMAGE, "image/jpeg"))
    subject = client._parse_subject({"id": 1, "type": 2, "name": "A"})

    embedded = await client.with_embedded_cover(subject)

    assert embedded.cover_url == (
        "data:image/png;base64," + base64.b64encode(PNG_IMAGE).decode("ascii")
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


def test_subject_rating_rank_supports_both_api_formats() -> None:
    assert BangumiClient._parse_subject({"rating": {"rank": 42}}).rank == 42
    assert BangumiClient._parse_subject({"rank": 24}).rank == 24
    assert (
        BangumiClient._parse_subject(
            {"rating": None, "images": None, "tags": None}
        ).rank
        == 0
    )


def test_cache_expires_unread_values_and_evicts_least_recently_used(
    monkeypatch,
) -> None:
    client = build_client()
    client.MAX_CACHE_ENTRIES = 2
    monkeypatch.setattr(client_module.time, "monotonic", lambda: 100.0)
    client._remember("expired", "large image", 1)
    client._remember("first", 1, 20)
    monkeypatch.setattr(client_module.time, "monotonic", lambda: 102.0)
    client._remember("second", 2, 20)
    assert "expired" not in client._cache
    assert client._cached("first") == 1
    client._remember("third", 3, 20)
    assert client._cached("second") is None
    assert client._cached("first") == 1


@pytest.mark.asyncio
async def test_invalid_episode_page_does_not_cache_partial_result() -> None:
    from astrbot_plugin_bangumi.src.bangumi_client import BangumiClientError

    client = build_client()
    client._request = AsyncMock(
        side_effect=[
            {"total": 101, "data": [{"ep": index} for index in range(100)]},
            {"data": None},
        ]
    )
    with pytest.raises(BangumiClientError, match="格式异常"):
        await client.get_episodes(1)
    assert client._cached("episodes:1") is None


@pytest.mark.asyncio
async def test_calendar_cache_rolls_over_at_cst_midnight(monkeypatch) -> None:
    client = build_client()
    client._request = AsyncMock(
        return_value=[
            {"weekday": {"id": 2}, "items": []},
            {"weekday": {"id": 3}, "items": []},
        ]
    )
    monkeypatch.setattr(client_module, "datetime", _fixed_datetime(2026, 7, 14, 23, 59))
    assert [day.weekday_id for day in await client.get_calendar() if day.is_today] == [
        2
    ]
    monkeypatch.setattr(client_module, "datetime", _fixed_datetime(2026, 7, 15, 0, 0))
    assert [day.weekday_id for day in await client.get_calendar() if day.is_today] == [
        3
    ]


@pytest.mark.asyncio
async def test_invalid_calendar_items_raise_client_error() -> None:
    from astrbot_plugin_bangumi.src.bangumi_client import BangumiClientError

    client = build_client()
    client._request = AsyncMock(return_value=[{"items": None}])
    with pytest.raises(BangumiClientError, match="格式异常"):
        await client.get_calendar()


@pytest.mark.asyncio
async def test_disk_cover_survives_client_restart_and_memory_expiration(
    tmp_path, monkeypatch
) -> None:
    directory = tmp_path / "covers"
    first_client = build_client(directory)
    first_client._request_bytes = AsyncMock(return_value=(PNG_IMAGE, "image/png"))
    subject = first_client._parse_subject({"id": 1, "type": 2, "name": "Example"})
    first_result = await first_client.with_embedded_cover(subject)
    first_client._request_bytes.assert_awaited_once()

    # A fresh client has no memory entries. Passing time must not expire disk covers.
    monkeypatch.setattr(client_module.time, "monotonic", lambda: 10000000.0)
    second_client = build_client(directory)
    second_client._request_bytes = AsyncMock(
        side_effect=AssertionError("unexpected download")
    )
    assert await second_client.with_embedded_cover(subject) == first_result
    second_client._cache.clear()
    assert await second_client.with_embedded_cover(subject) == first_result
    second_client._request_bytes.assert_not_awaited()


@pytest.mark.asyncio
async def test_corrupt_disk_cover_is_downloaded_and_repaired(tmp_path) -> None:
    directory = tmp_path / "covers"
    directory.mkdir()
    (directory / "1.cover").write_bytes(b"truncated file")
    client = build_client(directory)
    client._request_bytes = AsyncMock(return_value=(PNG_IMAGE, "image/png"))
    subject = client._parse_subject({"id": 1})

    result = await client.with_embedded_cover(subject)

    assert result.cover_url.startswith("data:image/png;base64,")
    assert await client._cover_disk_cache.read(1) == (PNG_IMAGE, "image/png")
    client._request_bytes.assert_awaited_once()


@pytest.mark.asyncio
async def test_simultaneous_cover_requests_download_only_once(tmp_path) -> None:
    client = build_client(tmp_path / "covers")

    async def download(*args, **kwargs):
        await asyncio.sleep(0)
        return PNG_IMAGE, "image/png"

    client._request_bytes = AsyncMock(side_effect=download)
    subject = client._parse_subject({"id": 1})
    results = await asyncio.gather(
        *(client.with_embedded_cover(subject) for _ in range(10))
    )

    assert len({result.cover_url for result in results}) == 1
    client._request_bytes.assert_awaited_once()
    assert not client._cover_locks


@pytest.mark.asyncio
async def test_cover_disk_failure_preserves_display_and_memory_cache(tmp_path) -> None:
    directory = tmp_path / "not-a-directory"
    directory.write_text("blocked")
    client = build_client(directory)
    client._request_bytes = AsyncMock(return_value=(PNG_IMAGE, "image/png"))
    subject = client._parse_subject({"id": 1})

    assert (await client.with_embedded_cover(subject)).cover_url.startswith(
        "data:image/png;base64,"
    )
    await client.with_embedded_cover(subject)
    client._request_bytes.assert_awaited_once()


@pytest.mark.asyncio
async def test_http_error_page_is_never_saved_as_cover(tmp_path) -> None:
    client = build_client(tmp_path / "covers")
    client._request_bytes = AsyncMock(
        return_value=(b"<html>proxy error</html>", "image/jpeg")
    )
    subject = client._parse_subject({"id": 1})

    assert await client.with_embedded_cover(subject) == subject
    assert not (tmp_path / "covers" / "1.cover").exists()
    assert client._cached("cover:1") is None
