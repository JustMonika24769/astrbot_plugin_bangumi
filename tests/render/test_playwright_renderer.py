from unittest.mock import AsyncMock

import pytest

from astrbot_plugin_bangumi.src.render.base_renderer import BaseRenderer
from astrbot_plugin_bangumi.src.render.calendar_renderer import CalendarRenderer
from astrbot_plugin_bangumi.tests.render.image_assertions import assert_png_image

INLINE_HTML = """
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <title>Playwright smoke</title>
    <style>
      body {
        margin: 0;
        background: #eef2f6;
      }
      #card {
        width: 280px;
        height: 180px;
        box-sizing: border-box;
        margin: 20px;
        padding: 16px;
        border: 2px solid #2b3440;
        background: #ffffff;
        color: #111827;
        font: 16px/1.4 sans-serif;
      }
    </style>
  </head>
  <body>
    <main id="card">
      <h1>Bangumi</h1>
      <p>Local Playwright smoke test.</p>
    </main>
  </body>
</html>
"""


def _fail_if_pillow_branch_is_used(*args: object, **kwargs: object) -> None:
    raise AssertionError("HTML mode should not fall back to Pillow rendering")


@pytest.mark.asyncio
async def test_calendar_html_mode_routes_to_local_browser_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = CalendarRenderer(render_mode="html")
    local_render = AsyncMock(return_value="browser-b64")

    monkeypatch.setattr(renderer, "_render_locally", local_render)
    monkeypatch.setattr(
        renderer,
        "_generate_html",
        lambda template_path, render_data, sub_dir="": INLINE_HTML,
    )
    monkeypatch.setattr(
        "astrbot_plugin_bangumi.src.render.calendar_renderer._draw_calendar_card_image",
        _fail_if_pillow_branch_is_used,
    )

    result = await renderer.render_calendar(
        [
            {
                "weekday": {"id": 1, "cn": "星期一"},
                "items": [{"name_cn": "相反的你和我"}],
            }
        ]
    )

    assert result == "browser-b64"
    local_render.assert_awaited_once()
    call = local_render.await_args
    assert call is not None
    assert call.kwargs["template_path"] == "calendar/calendar.html"
    assert call.kwargs["selector"] == ".container"
    assert call.kwargs["headless"] is True
    assert call.kwargs["timeout"] == 30000
    assert call.kwargs["max_retries"] == 3


@pytest.mark.asyncio
async def test_playwright_runtime_smoke_with_inline_html() -> None:
    renderer = BaseRenderer(render_mode="html")

    try:
        payload = await renderer._capture_screenshot(
            html_content=INLINE_HTML,
            selector="#card",
            headless=True,
            timeout=10000,
        )
    except RuntimeError as exc:
        if "无法创建浏览器页面" in str(exc):
            pytest.skip("Playwright browser binaries are unavailable")
        raise

    assert payload is not None

    assert_png_image(payload, require_non_blank=True)
