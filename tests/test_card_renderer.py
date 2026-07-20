from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from jinja2 import Environment

from astrbot_plugin_bangumi.src.card_renderer import CardRenderError, T2ICardRenderer
from astrbot_plugin_bangumi.src.entities import SubscriptionView


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


@pytest.mark.asyncio
async def test_renderer_rejects_html_error_page_as_image(
    html_render: AsyncMock,
    subject,
    tmp_path: Path,
) -> None:
    error_page = tmp_path / "response.jpg"
    error_page.write_text("<!doctype html><title>522 timeout</title>", encoding="utf-8")
    html_render.return_value = str(error_page)
    renderer = T2ICardRenderer(html_render)

    with pytest.raises(CardRenderError, match="非图片文件"):
        await renderer.subject_card(subject)


@pytest.mark.asyncio
async def test_subscription_card_contains_date_weekday_and_time(
    html_render: AsyncMock,
) -> None:
    renderer = T2ICardRenderer(html_render)
    subscription = SubscriptionView(
        session_id="onebot:GroupMessage:1",
        subject_id="1",
        title="示例动画",
        cover_url="",
        total_episodes=12,
        current_episode=2,
        last_notified_episode=2,
        broadcast_date="2026-07-15",
        broadcast_time="23:30",
        last_checked_at=None,
        subject_error=None,
        delivery_error=None,
    )

    await renderer.subscriptions_card([subscription])

    data = html_render.await_args.args[1]["subscriptions"][0]
    assert data["broadcast_schedule"] == "首播 2026-07-15 · 每周三 23:30"
