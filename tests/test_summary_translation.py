from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_bangumi.src.app.summary_translation import (
    summary_needs_chinese_translation,
    translate_text_to_chinese,
)


def test_translation_detection_handles_japanese_and_chinese() -> None:
    assert summary_needs_chinese_translation("これは简介です")
    assert not summary_needs_chinese_translation("这是一段中文简介")
    assert not summary_needs_chinese_translation("")


@pytest.mark.asyncio
@pytest.mark.parametrize("completion", [None, "", "  ", 123, "译文"])
async def test_translation_handles_invalid_completion(completion) -> None:
    context = MagicMock()
    context.get_using_provider.return_value.meta.return_value = SimpleNamespace(
        id="chat"
    )
    context.llm_generate = AsyncMock(
        return_value=SimpleNamespace(completion_text=completion)
    )

    result = await translate_text_to_chinese(context, "原文", feature_name="测试")

    assert result == ("译文" if completion == "译文" else "原文")


@pytest.mark.asyncio
async def test_translation_failure_preserves_original_text() -> None:
    context = MagicMock()
    context.get_using_provider.return_value.meta.return_value = SimpleNamespace(
        id="chat"
    )
    context.llm_generate = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    assert (
        await translate_text_to_chinese(context, "原文", feature_name="测试") == "原文"
    )
