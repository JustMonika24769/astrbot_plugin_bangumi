from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_bangumi.src.adapters import (
    AstrBotResponseMapper,
    StarToolsGroupNotifier,
)
from astrbot_plugin_bangumi.src.app import AppImages, AppText


def test_response_mapper_maps_text_to_plain_result() -> None:
    event = MagicMock()
    event.plain_result.return_value = "plain"

    result = AstrBotResponseMapper().to_event_result(event, AppText("hello"))

    assert result == "plain"
    event.plain_result.assert_called_once_with("hello")
    event.chain_result.assert_not_called()


def test_response_mapper_maps_images_to_chain_result() -> None:
    event = MagicMock()
    event.chain_result.return_value = "chain"

    result = AstrBotResponseMapper().to_event_result(event, AppImages(("a", "b")))

    assert result == "chain"
    event.chain_result.assert_called_once()
    components = event.chain_result.call_args.args[0]
    assert [component.file for component in components] == [
        "base64://a",
        "base64://b",
    ]
    event.plain_result.assert_not_called()


@pytest.mark.asyncio
async def test_group_notifier_sends_image_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    send_message = AsyncMock()
    monkeypatch.setattr(
        "astrbot_plugin_bangumi.src.adapters.astrbot.StarTools.send_message_by_id",
        send_message,
    )

    await StarToolsGroupNotifier().send_episode_update(
        group_id="group",
        image_base64="image",
        fallback_text="fallback",
    )

    send_message.assert_awaited_once()
    assert send_message.call_args.kwargs["type"] == "GroupMessage"
    assert send_message.call_args.kwargs["id"] == "group"
    message_chain = send_message.call_args.kwargs["message_chain"]
    assert message_chain.chain[0].file == "base64://image"


@pytest.mark.asyncio
async def test_group_notifier_sends_fallback_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    send_message = AsyncMock()
    monkeypatch.setattr(
        "astrbot_plugin_bangumi.src.adapters.astrbot.StarTools.send_message_by_id",
        send_message,
    )

    await StarToolsGroupNotifier().send_episode_update(
        group_id="group",
        image_base64=None,
        fallback_text="fallback",
    )

    message_chain = send_message.call_args.kwargs["message_chain"]
    assert message_chain.chain[0].text == "fallback"
