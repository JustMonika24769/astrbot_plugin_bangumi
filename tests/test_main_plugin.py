import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

BangumiPlugin = importlib.import_module("astrbot_plugin_bangumi.main").BangumiPlugin


def test_resolve_session_key_prefers_group_id() -> None:
    event = SimpleNamespace(
        session_id="session", message_obj=SimpleNamespace(group_id="group")
    )

    assert BangumiPlugin._resolve_session_key(event) == "group"


def test_parse_subscribe_selection() -> None:
    assert BangumiPlugin._parse_subscribe_selection("/追番 2") == 2
    assert BangumiPlugin._parse_subscribe_selection("追番 3") == 3
    assert BangumiPlugin._parse_subscribe_selection("追番 abc") is None


def test_should_requeue_subscribe_command() -> None:
    assert BangumiPlugin._should_requeue_subscribe_command("/bgm test") is True
    assert BangumiPlugin._should_requeue_subscribe_command("追番 巨人") is True
    assert BangumiPlugin._should_requeue_subscribe_command("/追番 1") is False
    assert BangumiPlugin._should_requeue_subscribe_command("普通消息") is False


@pytest.mark.asyncio
async def test_search_anime_dispatches_type_and_tag() -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    plugin.search_service = MagicMock()
    plugin.search_service.handle_subject_search = _async_gen_mock("ok")
    event = _event()

    results = [
        result async for result in BangumiPlugin.search_anime(plugin, event, "key", 2)
    ]

    assert results == ["ok"]
    plugin.search_service.handle_subject_search.assert_called_once_with(
        event, "key", 2, subject_type=[2], subject_tags=["TV"]
    )


@pytest.mark.asyncio
async def test_today_dispatches_to_search_service() -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    plugin.search_service = MagicMock()
    plugin.search_service.handle_today = _async_gen_mock("today")
    event = _event()

    results = [result async for result in BangumiPlugin.today(plugin, event)]

    assert results == ["today"]
    plugin.search_service.handle_today.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_subscribe_single_candidate_uses_subject_id() -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    plugin.config_manager = MagicMock()
    plugin.config_manager.get_max_fuzzy_results.return_value = 5
    plugin.subscription_service = MagicMock()
    plugin.subscription_service.get_subscribe_candidates = AsyncMock(
        return_value=(None, [{"subject_id": "1", "name": "番"}])
    )
    plugin.subscription_service.subscribe_by_subject_id = AsyncMock(return_value="done")
    event = _event(group_id="group")

    results = [result async for result in BangumiPlugin.subscribe(plugin, event, "番")]

    assert results == ["done"]
    plugin.subscription_service.subscribe_by_subject_id.assert_awaited_once_with(
        group_id="group", subject_id="1"
    )


def _event(group_id: str = "group") -> MagicMock:
    event = MagicMock()
    event.session_id = "session"
    event.message_obj = SimpleNamespace(group_id=group_id)
    event.plain_result = MagicMock(side_effect=lambda text: text)
    event.chain_result = MagicMock(side_effect=lambda chain: chain)
    return event


def _async_gen_mock(value: object) -> MagicMock:
    async def gen(*args: object, **kwargs: object):
        yield value

    return MagicMock(side_effect=gen)
