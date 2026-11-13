from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

from astrbot_plugin_bangumi.src import webui as module
from astrbot_plugin_bangumi.src.db import BangumiRepository
from astrbot_plugin_bangumi.src.entities import (
    CalendarDay,
    SubscribeResult,
    UpdateReport,
)
from astrbot_plugin_bangumi.src.webui import BangumiWebUI


@pytest.fixture
def webui(tmp_path, context, subject, episode):
    repository = BangumiRepository(str(tmp_path / "data.db"))
    api = MagicMock()
    api.get_subject = AsyncMock(return_value=subject)
    api.search_subjects = AsyncMock(return_value=[subject])
    api.get_calendar = AsyncMock(
        return_value=[CalendarDay(1, "星期一", (subject,), True)]
    )
    tracking = MagicMock()
    tracking._check_lock = asyncio.Lock()
    tracking.subscribe = AsyncMock(return_value=SubscribeResult(subject, episode, True))
    tracking.check_updates = AsyncMock(
        return_value=UpdateReport(subjects_total=1, subjects_checked=1)
    )
    controller = BangumiWebUI(context, api, repository, tracking)
    yield controller
    repository.close()


def body(monkeypatch, payload):
    monkeypatch.setattr(module, "request_body", AsyncMock(return_value=payload))


@pytest.mark.asyncio
async def test_webui_lists_all_sessions_and_status_without_credentials(
    webui, subject
) -> None:
    webui.repository.subscribe(
        "onebot-main:GroupMessage:123", subject, baseline_episode=1
    )
    webui.repository.subscribe(
        "onebot-main:FriendMessage:456", subject, baseline_episode=2
    )
    webui.repository.mark_checked(str(subject.id), current_episode=3)
    webui.repository.mark_delivery_error(
        "onebot-main:GroupMessage:123", str(subject.id), "发送失败"
    )

    result = await webui.state()

    assert len(result["subscriptions"]) == 2
    assert all(row["pending"] for row in result["subscriptions"])
    assert result["platforms"] == [{"id": "onebot-main", "name": "aiocqhttp"}]
    assert "access_token" not in json.dumps(result)
    assert result["checking"] is False


@pytest.mark.asyncio
async def test_webui_search_only_anime(webui, monkeypatch, subject) -> None:
    body(monkeypatch, {"query": "示例"})
    result = await webui.search()
    assert result["subjects"][0]["title"] == subject.title
    webui.api.search_subjects.assert_awaited_once_with(
        "示例", limit=10, subject_types=(2,)
    )


@pytest.mark.asyncio
async def test_webui_subscribe_uses_existing_tracker(
    webui, monkeypatch, subject
) -> None:
    body(
        monkeypatch,
        {"subject_id": str(subject.id), "session_id": "onebot-main:GroupMessage:123"},
    )
    assert await webui.subscribe() == {"created": True, "title": subject.title}
    webui.tracking.subscribe.assert_awaited_once_with(
        "onebot-main:GroupMessage:123", subject
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session",
    [
        "unknown:GroupMessage:123",
        "onebot-main:Bad:123",
        "onebot-main:GroupMessage:",
        "123",
    ],
)
async def test_webui_rejects_invalid_destination(
    webui, monkeypatch, subject, session
) -> None:
    body(monkeypatch, {"subject_id": str(subject.id), "session_id": session})
    with pytest.raises(ValueError):
        await webui.subscribe()
    webui.api.get_subject.assert_not_awaited()


@pytest.mark.asyncio
async def test_webui_rejects_non_anime(webui, monkeypatch, subject) -> None:
    webui.api.get_subject.return_value = replace(subject, type=1)
    body(
        monkeypatch,
        {"subject_id": str(subject.id), "session_id": "onebot-main:GroupMessage:123"},
    )
    with pytest.raises(ValueError, match="仅支持动画"):
        await webui.subscribe()
    webui.tracking.subscribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_webui_unsubscribe_preserves_other_sessions(
    webui, monkeypatch, subject
) -> None:
    for session in ["a", "b"]:
        webui.repository.subscribe(session, subject, baseline_episode=0)
    body(monkeypatch, {"subject_id": str(subject.id), "session_id": "a"})
    assert await webui.unsubscribe() == {"removed": True}
    assert webui.repository.list_subscriptions("a") == []
    assert len(webui.repository.list_subscriptions("b")) == 1
    with pytest.raises(ValueError, match="已不存在"):
        await webui.unsubscribe()


@pytest.mark.asyncio
async def test_webui_background_check_records_report_and_rejects_duplicates(
    webui, monkeypatch, subject
) -> None:
    webui.repository.subscribe("a", subject, baseline_episode=0)
    gate = asyncio.Event()

    async def check(**kwargs):
        await gate.wait()
        return UpdateReport(subjects_total=1, subjects_checked=1, delivered=1)

    webui.tracking.check_updates.side_effect = check
    body(monkeypatch, {"session_id": "a"})
    result = await webui.check()
    assert result["job_id"] == webui.jobs[0]["id"]
    assert (await webui.state())["checking"] is True
    with pytest.raises(ValueError, match="已有检查"):
        await webui.check()
    gate.set()
    await webui._task
    assert webui.jobs[0]["status"] == "done"
    assert webui.jobs[0]["report"]["delivered"] == 1
    webui.tracking.check_updates.assert_awaited_once_with(session_id="a", refresh=True)
    assert (await webui.state())["checking"] is False


@pytest.mark.asyncio
async def test_webui_check_failure_is_reported(webui, monkeypatch, subject) -> None:
    webui.repository.subscribe("a", subject, baseline_episode=0)
    body(monkeypatch, {})
    webui.tracking.check_updates.side_effect = RuntimeError("private internal detail")
    await webui.check()
    await webui._task
    assert webui.jobs[0]["status"] == "error"
    assert "private internal detail" not in webui.jobs[0]["summary"]


@pytest.mark.asyncio
async def test_webui_refuses_empty_or_busy_check(webui, monkeypatch) -> None:
    body(monkeypatch, {})
    with pytest.raises(ValueError, match="还没有订阅"):
        await webui.check()
    async with webui.tracking._check_lock:
        with pytest.raises(ValueError, match="已有检查"):
            await webui.check()


@pytest.mark.asyncio
async def test_webui_closes_jobs_and_only_removes_owned_routes(
    webui, monkeypatch, subject
) -> None:
    webui.context.registered_web_apis = []
    webui.context.register_web_api.side_effect = lambda *args: (
        webui.context.registered_web_apis.append(args)
    )
    webui.register()
    assert len(webui.context.registered_web_apis) == 8
    owned_handler = webui.context.registered_web_apis[0][1]
    unrelated = ("/other", AsyncMock(), ["GET"], "other")
    webui.context.registered_web_apis.append(unrelated)
    webui.repository.subscribe("a", subject, baseline_episode=0)
    body(monkeypatch, {})

    # Ensure cancellation is exercised while the coroutine is waiting.
    async def long_check(**kwargs):
        await asyncio.Event().wait()

    webui.tracking.check_updates.side_effect = long_check
    await webui.check()
    await asyncio.sleep(0)
    await webui.close()
    assert webui._task.cancelled()
    assert webui.jobs[0]["status"] == "cancelled"
    assert webui.context.registered_web_apis == [unrelated]
    assert (await owned_handler())["status"] == "error"


@pytest.mark.asyncio
async def test_webui_guard_does_not_leak_unexpected_errors(webui) -> None:
    handler = webui._guard(AsyncMock(side_effect=RuntimeError("secret")))
    result = await handler()
    assert result["status"] == "error"
    assert "secret" not in result["message"]


@pytest.mark.asyncio
async def test_webui_calendar_contains_titles(webui, subject) -> None:
    result = await webui.calendar()
    assert result["days"][0]["items"][0]["title"] == subject.title


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [b"[]", b"null", b"invalid", b'{"query":"anime"}'])
async def test_webui_public_request_adapter(raw) -> None:
    from astrbot.api.web import PluginRequest, bind_request_context

    async def receive():
        return {"type": "http.request", "body": raw}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )
    with bind_request_context(PluginRequest(request, username="admin")):
        if raw == b'{"query":"anime"}':
            assert await module.request_body() == {"query": "anime"}
        else:
            with pytest.raises(ValueError, match="JSON 对象"):
                await module.request_body()


@pytest.mark.asyncio
async def test_webui_cover_downloads_by_id_using_shared_client(
    webui, monkeypatch, subject
) -> None:
    embedded = "data:image/png;base64,aW1hZ2U="
    webui.api.with_embedded_cover = AsyncMock(
        return_value=replace(subject, cover_url=embedded)
    )
    body(monkeypatch, {"subject_id": str(subject.id), "url": "http://169.254.169.254/"})
    assert await webui.cover() == {"cover_url": embedded}
    downloaded = webui.api.with_embedded_cover.await_args.args[0]
    assert downloaded.id == subject.id
    assert downloaded.cover_url == ""
    webui.api.get_subject.assert_not_awaited()


@pytest.mark.asyncio
async def test_webui_cover_failure_does_not_return_unusable_remote_url(
    webui, monkeypatch, subject
) -> None:
    from astrbot_plugin_bangumi.src.bangumi_client import BangumiClientError

    webui.api.with_embedded_cover = AsyncMock(return_value=subject)
    body(monkeypatch, {"subject_id": str(subject.id)})
    with pytest.raises(BangumiClientError, match="暂时无法下载"):
        await webui.cover()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", ["https://example.com/cover.jpg", "../secret", "0", "-1", None]
)
async def test_webui_cover_rejects_invalid_ids(webui, monkeypatch, value) -> None:
    body(monkeypatch, {"subject_id": value})
    with pytest.raises(ValueError):
        await webui.cover()
    webui.api.with_embedded_cover.assert_not_called()


@pytest.mark.asyncio
async def test_webui_subject_contains_details_and_actual_episode_dates(
    webui, monkeypatch, subject, episode
):
    webui.api.get_episodes = AsyncMock(return_value=[episode])
    webui.repository.subscribe(
        "onebot-main:GroupMessage:123",
        subject,
        baseline_episode=0,
        broadcast_date="2026-11-13",
        broadcast_time="23:30",
    )
    body(monkeypatch, {"subject_id": str(subject.id)})
    result = await webui.subject()
    assert result["subject"]["title"] == subject.title
    assert result["weekly_schedule"] == "常规每周五 23:30（北京时间）"
    assert result["episodes"][0]["air_date"] == episode.air_date
    assert "message" in result["airing"]
    state = await webui.state()
    assert state["subscriptions"][0]["weekly_schedule"] == result["weekly_schedule"]


@pytest.mark.asyncio
async def test_webui_subject_episode_failure_keeps_description(
    webui, monkeypatch, subject
):
    from astrbot_plugin_bangumi.src.bangumi_client import BangumiClientError

    webui.api.get_episodes = AsyncMock(side_effect=BangumiClientError("upstream"))
    body(monkeypatch, {"subject_id": str(subject.id)})
    result = await webui.subject()
    assert result["subject"]["title"] == subject.title
    assert result["episodes"] == []
    assert "暂时无法读取" in result["airing"]["message"]


@pytest.mark.asyncio
async def test_webui_subject_invalid_id_is_rejected(webui, monkeypatch):
    body(monkeypatch, {"subject_id": "../secret"})
    with pytest.raises(ValueError):
        await webui.subject()
    webui.api.get_subject.assert_not_awaited()
