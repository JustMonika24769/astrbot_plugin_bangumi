import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_bangumi.src.app import AppText

BangumiPlugin = importlib.import_module("astrbot_plugin_bangumi.main").BangumiPlugin


def test_resolve_session_key_prefers_group_id() -> None:
    event = SimpleNamespace(
        session_id="session", message_obj=SimpleNamespace(group_id="group")
    )

    assert BangumiPlugin._resolve_session_key(event) == "group"


def test_parse_subscribe_selection() -> None:
    assert BangumiPlugin._parse_subscribe_selection("1") == 1
    assert BangumiPlugin._parse_subscribe_selection("  10  ") == 10
    assert BangumiPlugin._parse_subscribe_selection("/追番 2") == 2
    assert BangumiPlugin._parse_subscribe_selection("追番 3") == 3
    assert BangumiPlugin._parse_subscribe_selection("追番 abc") is None
    assert BangumiPlugin._parse_subscribe_selection("1 abc") is None


def test_format_subscribe_selection_hint_mentions_bare_number() -> None:
    assert (
        BangumiPlugin._format_subscribe_selection_hint(10)
        == "请输入 1-10 的序号,例如 `1` 或 `/追番 1`"
    )


def test_should_requeue_subscribe_command() -> None:
    assert BangumiPlugin._should_requeue_subscribe_command("/bgm test") is True
    assert BangumiPlugin._should_requeue_subscribe_command("追番 巨人") is True
    assert BangumiPlugin._should_requeue_subscribe_command("1") is False
    assert BangumiPlugin._should_requeue_subscribe_command("/追番 1") is False
    assert BangumiPlugin._should_requeue_subscribe_command("普通消息") is False


def test_normalize_episode_card_template_accepts_names_and_order() -> None:
    assert BangumiPlugin._normalize_episode_card_template("1") == "pastel_lightbox"
    assert BangumiPlugin._normalize_episode_card_template("2") == "editorial_digest"
    assert BangumiPlugin._normalize_episode_card_template("3") == "cinematic_poster"
    assert (
        BangumiPlugin._normalize_episode_card_template("cinematic-poster")
        == "cinematic_poster"
    )
    assert BangumiPlugin._normalize_episode_card_template("默认") == "cinematic_poster"
    assert BangumiPlugin._normalize_episode_card_template("unknown") is None


def test_build_proxy_url_requires_host_and_port() -> None:
    assert BangumiPlugin._build_proxy_url("", "7890") is None
    assert BangumiPlugin._build_proxy_url("127.0.0.1", "") is None


def test_build_proxy_url_adds_default_scheme() -> None:
    assert (
        BangumiPlugin._build_proxy_url("127.0.0.1", "7890") == "http://127.0.0.1:7890"
    )


def test_build_proxy_url_trims_host_and_port() -> None:
    assert (
        BangumiPlugin._build_proxy_url(" http://proxy.local ", " 8080 ")
        == "http://proxy.local:8080"
    )


def test_build_proxy_url_preserves_scheme_and_existing_port() -> None:
    assert (
        BangumiPlugin._build_proxy_url("socks5://127.0.0.1:1080", "7890")
        == "socks5://127.0.0.1:1080"
    )
    assert (
        BangumiPlugin._build_proxy_url("proxy.local:1080", "7890")
        == "http://proxy.local:1080"
    )


@pytest.mark.asyncio
async def test_search_anime_dispatches_type_and_tag() -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    plugin.search_service = MagicMock()
    plugin.search_service.handle_subject_search = AsyncMock(return_value=AppText("ok"))
    plugin.response_mapper = _response_mapper()
    event = _event()

    results = [
        result async for result in BangumiPlugin.search_anime(plugin, event, "key", 2)
    ]

    assert results == ["ok"]
    plugin.search_service.handle_subject_search.assert_awaited_once_with(
        query="key", top_k=2, subject_type=[2], subject_tags=["TV"]
    )
    plugin.response_mapper.to_event_result.assert_called_once_with(event, AppText("ok"))


@pytest.mark.asyncio
async def test_today_dispatches_to_search_service() -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    plugin.search_service = MagicMock()
    plugin.search_service.handle_today = AsyncMock(return_value=AppText("today"))
    plugin.response_mapper = _response_mapper()
    event = _event()

    results = [result async for result in BangumiPlugin.today(plugin, event)]

    assert results == ["today"]
    plugin.search_service.handle_today.assert_awaited_once_with()
    plugin.response_mapper.to_event_result.assert_called_once_with(
        event, AppText("today")
    )


@pytest.mark.asyncio
async def test_episode_card_template_command_shows_current_template() -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    plugin.config_manager = MagicMock()
    plugin.config_manager.get_episode_card_template.return_value = "cinematic_poster"
    event = _event()

    results = [
        result async for result in BangumiPlugin.episode_card_template(plugin, event)
    ]

    assert len(results) == 1
    assert "当前单集卡片模板: cinematic_poster" in results[0]
    assert "1. pastel_lightbox" in results[0]
    assert "3. cinematic_poster" in results[0]
    plugin.config_manager.set_episode_card_template.assert_not_called()
    plugin.config_manager.save_config.assert_not_called()


@pytest.mark.asyncio
async def test_episode_card_template_command_updates_config() -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    plugin.config_manager = MagicMock()
    event = _event()

    results = [
        result
        async for result in BangumiPlugin.episode_card_template(plugin, event, "2")
    ]

    assert results == ["✅ 已切换单集卡片模板为 editorial_digest - Episode digest"]
    plugin.config_manager.set_episode_card_template.assert_called_once_with(
        "editorial_digest"
    )
    plugin.config_manager.save_config.assert_called_once()


@pytest.mark.asyncio
async def test_episode_card_template_command_rejects_unknown_template() -> None:
    plugin = BangumiPlugin.__new__(BangumiPlugin)
    plugin.config_manager = MagicMock()
    event = _event()

    results = [
        result
        async for result in BangumiPlugin.episode_card_template(plugin, event, "bad")
    ]

    assert len(results) == 1
    assert "❌ 未知单集卡片模板: bad" in results[0]
    plugin.config_manager.set_episode_card_template.assert_not_called()
    plugin.config_manager.save_config.assert_not_called()


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


def _response_mapper() -> MagicMock:
    mapper = MagicMock()
    mapper.to_event_result = MagicMock(
        side_effect=lambda _event, response: response.text
        if isinstance(response, AppText)
        else response
    )
    return mapper
