from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_bangumi.src.card_renderer import CardRenderError
from astrbot_plugin_bangumi.src.entities import SubscribeResult

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

    result = await plugin._search(event, "示例", 3)

    assert result == "IMAGE:card.jpg"
    plugin.cards.search_card.assert_awaited_once()


@pytest.mark.asyncio
async def test_subscribe_ambiguous_result_requires_explicit_id(subject) -> None:
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

    results = [
        result async for result in BangumiPlugin.subscribe(plugin, event, "示例")
    ]

    assert results == ["IMAGE:choices.jpg"]
    plugin.tracking.subscribe.assert_not_called()


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
        result async for result in BangumiPlugin.subscribe(plugin, event, str(subject.id))
    ]

    assert len(results) == 1
    assert "订阅成功" in results[0]
    assert "确认卡片渲染失败" in results[0]


def _event() -> MagicMock:
    event = MagicMock()
    event.unified_msg_origin = "aiocqhttp:GroupMessage:123"
    event.message_obj = SimpleNamespace(group_id="123")
    event.image_result.side_effect = lambda path: f"IMAGE:{path}"
    event.plain_result.side_effect = lambda text: text
    event.chain_result.side_effect = lambda chain: chain
    return event
