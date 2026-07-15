from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from jinja2 import Environment

from astrbot_plugin_bangumi.src.card_renderer import CardRenderError, T2ICardRenderer


@pytest.mark.asyncio
async def test_subject_card_uses_astrbot_html_render(
    html_render: AsyncMock, subject, episode
) -> None:
    renderer = T2ICardRenderer(html_render, quality=92)

    result = await renderer.subject_card(subject, latest=episode, subscribed=True)

    assert result.endswith("rendered.jpg")
    call = html_render.await_args
    assert "Subject dossier" in call.args[0]
    assert call.args[1]["subject"]["id"] == 454083
    assert call.kwargs["return_url"] is False
    assert call.kwargs["options"] == {
        "full_page": True,
        "type": "jpeg",
        "quality": 92,
    }


@pytest.mark.asyncio
async def test_all_templates_compile_with_jinja(html_render: AsyncMock) -> None:
    renderer = T2ICardRenderer(html_render)
    environment = Environment(autoescape=True)

    for name in [
        "subject",
        "search",
        "calendar",
        "subscriptions",
        "update",
        "report",
        "help",
    ]:
        template = renderer._template(name)
        environment.from_string(template)
        assert "width: 1280px" in template
        assert "/*__CARD_CSS__*/" not in template


@pytest.mark.asyncio
async def test_renderer_wraps_t2i_failure(html_render: AsyncMock, subject) -> None:
    html_render.side_effect = RuntimeError("t2i down")
    renderer = T2ICardRenderer(html_render)

    with pytest.raises(CardRenderError, match="t2i down"):
        await renderer.subject_card(subject)
