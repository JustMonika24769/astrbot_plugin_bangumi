from __future__ import annotations

import asyncio
import importlib
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot.core.utils.session_waiter import SessionWaiter

from astrbot_plugin_bangumi.src.card_renderer import CardRenderError
from astrbot_plugin_bangumi.src.entities import SubscribeResult, SubscriptionView

module = importlib.import_module("astrbot_plugin_bangumi.main")
BangumiPlugin = module.BangumiPlugin


def test_session_id_uses_standard_origin_and_migrates_legacy_qq() -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    plugin.repository = MagicMock()
    plugin.repository.migrate_session_aliases.return_value = 1
    telegram = SimpleNamespace(
        unified_msg_origin="telegram:GroupMessage:123",
        message_obj=SimpleNamespace(group_id="123"),
    )
    qq = SimpleNamespace(
        unified_msg_origin="aiocqhttp:group:456",
        message_obj=SimpleNamespace(group_id="456"),
    )

    assert plugin._session_id(telegram) == "telegram:GroupMessage:123"
    assert plugin._session_id(qq) == "aiocqhttp:GroupMessage:456"
    plugin.repository.migrate_session_aliases.assert_any_call(
        "aiocqhttp:GroupMessage:456",
        {"456", "aiocqhttp:group:456"},
    )


@pytest.mark.asyncio
async def test_search_multiple_subjects_returns_one_t2i_card(subject) -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    plugin.config = SimpleNamespace(search_limit=5)
    plugin.api = MagicMock()
    plugin.api.search_subjects = AsyncMock(return_value=[subject, subject])
    plugin.api.with_embedded_cover = AsyncMock(side_effect=lambda value: value)
    plugin.cards = MagicMock()
    plugin.cards.search_card = AsyncMock(return_value="card.jpg")
    plugin.tracking = MagicMock()
    plugin.repository = MagicMock()
    event = _event()

    results = plugin._search(event, "示例", 3)
    result = await anext(results)
    await results.aclose()

    assert result == "IMAGE:card.jpg"
    plugin.cards.search_card.assert_awaited_once()


@pytest.mark.asyncio
async def test_subscribe_ambiguous_result_waits_for_sequence(subject) -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    plugin.config = SimpleNamespace(search_limit=5)
    plugin.api = MagicMock()
    plugin.api.search_subjects = AsyncMock(return_value=[subject, subject])
    plugin.api.with_embedded_cover = AsyncMock(side_effect=lambda value: value)
    plugin.cards = MagicMock()
    plugin.cards.search_card = AsyncMock(return_value="choices.jpg")
    plugin.tracking = MagicMock()
    plugin.repository = MagicMock()
    event = _event()

    results = BangumiPlugin.subscribe(plugin, event, "示例")
    first_result = await anext(results)
    await results.aclose()

    assert first_result == "IMAGE:choices.jpg"
    plugin.tracking.subscribe.assert_not_called()


@pytest.mark.asyncio
async def test_numeric_reply_selects_subject_and_retries_invalid_index(subject) -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    second_subject = replace(subject, id=subject.id + 1, name_cn="第二个结果")
    event = _event("bgm番剧 示例")
    selected = AsyncMock(return_value="SELECTED")

    waiting = asyncio.create_task(
        plugin._wait_for_subject_selection(
            event,
            [subject, second_subject],
            selected,
        )
    )
    await asyncio.sleep(0)
    selection_id = (
        "astrbot-plugin-bangumi:selection:"
        f"{event.unified_msg_origin}:{event.get_sender_id()}"
    )

    invalid_reply = _event("3")
    await SessionWaiter.trigger(selection_id, invalid_reply)
    invalid_reply.send.assert_awaited_once()
    assert not waiting.done()

    valid_reply = _event("2")
    await SessionWaiter.trigger(selection_id, valid_reply)
    await waiting

    selected.assert_awaited_once_with(valid_reply, second_subject)
    valid_reply.send.assert_awaited_once_with("SELECTED")


@pytest.mark.asyncio
async def test_subscribe_uses_complete_multiword_query(subject) -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    plugin.config = SimpleNamespace(search_limit=5)
    plugin.api = MagicMock()
    plugin.api.search_subjects = AsyncMock(return_value=[])
    plugin.cards = MagicMock()
    plugin.tracking = MagicMock()
    plugin.repository = MagicMock()
    plugin.repository.migrate_session_aliases.return_value = 0
    event = _event("追番 攻壳机动队 ghost in the shell")

    results = [
        result async for result in BangumiPlugin.subscribe(plugin, event, "攻壳机动队")
    ]

    assert results == ["没有找到动画“攻壳机动队 ghost in the shell”"]
    plugin.api.search_subjects.assert_awaited_once_with(
        "攻壳机动队 ghost in the shell",
        limit=5,
        subject_types=(2,),
    )


def test_search_request_preserves_spaces_and_parses_optional_limit() -> None:
    event = _event("bgm番剧 攻壳机动队 ghost in the shell")

    query = BangumiPlugin._command_argument_text(
        event,
        ("bgm番剧", "bgm动漫"),
        "攻壳机动队",
    )

    assert query == "攻壳机动队 ghost in the shell"
    assert BangumiPlugin._search_request(f"{query} 5") == (query, 5)


@pytest.mark.asyncio
async def test_subscribe_reports_success_when_confirmation_card_fails(
    subject, episode
) -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    plugin.config = SimpleNamespace(
        search_limit=5,
        auto_translate_subject_summary=False,
    )
    plugin.api = MagicMock()
    plugin.api.search_subjects = AsyncMock(return_value=[subject])
    plugin.api.get_subject = AsyncMock(return_value=subject)
    plugin.api.with_embedded_cover = AsyncMock(return_value=subject)
    plugin.cards = MagicMock()
    plugin.cards.subject_card = AsyncMock(
        side_effect=CardRenderError("T2I unavailable")
    )
    plugin.tracking = MagicMock()
    plugin.tracking.subscribe = AsyncMock(
        return_value=SubscribeResult(subject, episode, True)
    )
    plugin.repository = MagicMock()
    plugin.context = MagicMock()
    event = _event()

    results = [
        result
        async for result in BangumiPlugin.subscribe(plugin, event, str(subject.id))
    ]

    assert len(results) == 1
    assert "订阅成功" in results[0]
    assert "确认卡片渲染失败" in results[0]


@pytest.mark.asyncio
async def test_broadcast_time_command_sets_date_and_time() -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    item = SubscriptionView(
        session_id="aiocqhttp:GroupMessage:123",
        subject_id="454083",
        title="示例动画",
        cover_url="",
        total_episodes=12,
        current_episode=2,
        last_notified_episode=2,
        broadcast_date=None,
        broadcast_time=None,
        last_checked_at=None,
        subject_error=None,
        delivery_error=None,
    )
    updated = replace(
        item,
        broadcast_date="2026-07-15",
        broadcast_time="23:30",
    )
    plugin.api = MagicMock()
    plugin.cards = MagicMock()
    plugin.tracking = MagicMock()
    plugin.repository = MagicMock()
    plugin.repository.migrate_session_aliases.return_value = 0
    plugin.repository.find_subscription.side_effect = [[item], [updated]]
    event = _event()

    results = [
        result
        async for result in BangumiPlugin.broadcast_time(
            plugin,
            event,
            "454083",
            "2026-07-15",
            "23:30",
        )
    ]

    plugin.repository.set_broadcast_schedule.assert_called_once_with(
        "454083",
        broadcast_date="2026-07-15",
        broadcast_time="23:30",
    )
    assert results == [
        "已将《示例动画》放送安排设置为：首播 2026-07-15 · 每周三 23:30（CST）"
    ]


@pytest.mark.asyncio
async def test_broadcast_time_command_keeps_date_when_only_time_changes() -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    item = SubscriptionView(
        session_id="aiocqhttp:GroupMessage:123",
        subject_id="454083",
        title="示例动画",
        cover_url="",
        total_episodes=12,
        current_episode=2,
        last_notified_episode=2,
        broadcast_date="2026-07-15",
        broadcast_time="22:00",
        last_checked_at=None,
        subject_error=None,
        delivery_error=None,
    )
    plugin.api = MagicMock()
    plugin.cards = MagicMock()
    plugin.tracking = MagicMock()
    plugin.repository = MagicMock()
    plugin.repository.migrate_session_aliases.return_value = 0
    plugin.repository.find_subscription.side_effect = [
        [item],
        [replace(item, broadcast_time="23:30")],
    ]
    event = _event()

    results = [
        result
        async for result in BangumiPlugin.broadcast_time(
            plugin, event, "454083", "23:30"
        )
    ]

    plugin.repository.set_broadcast_schedule.assert_called_once_with(
        "454083",
        broadcast_date="2026-07-15",
        broadcast_time="23:30",
    )
    assert "每周三 23:30" in results[0]


def _event(message: str = "") -> MagicMock:
    event = MagicMock()
    event.unified_msg_origin = "aiocqhttp:GroupMessage:123"
    event.message_obj = SimpleNamespace(group_id="123")
    event.get_message_str.return_value = message
    event.get_sender_id.return_value = "user-123"
    event.image_result.side_effect = lambda path: f"IMAGE:{path}"
    event.plain_result.side_effect = lambda text: text
    event.chain_result.side_effect = lambda chain: chain
    event.send = AsyncMock()
    return event
