import base64
from unittest.mock import AsyncMock

import pytest

from src.render import SubjectRenderer

DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7+ZMsAAAAASUVORK5CYII="
)


def build_subject_data() -> dict[str, object]:
    return {
        "date": "2026-01-11",
        "platform": "TV",
        "image_url": DATA_URI,
        "summary": (
            "总是活力充沛,却又很在意周遭目光的女孩与个性文静的男生,在校园生活中"
            "慢慢靠近彼此,是一部气质轻盈但情感推进很扎实的青春恋爱喜剧。"
        ),
        "name": "正反対な君と僕",
        "name_cn": "相反的你和我",
        "tags": [
            {"name": "恋爱", "count": 1356},
            {"name": "校园", "count": 1071},
            {"name": "漫画改", "count": 823},
            {"name": "TV", "count": 120},
        ],
        "infobox": [
            {"key": "中文名", "value": "相反的你和我"},
            {"key": "话数", "value": "12"},
            {"key": "放送开始", "value": "2026年1月11日"},
        ],
        "total_episodes": 12,
        "id": 525565,
        "type": 2,
        "episodes": [
            {"ep": 1, "type": 0, "airdate": "2026-01-11", "comment": 10},
            {"ep": 2, "type": 0, "airdate": "2026-01-18", "comment": 5},
            {"ep": 3, "type": 0, "airdate": "2026-01-25", "comment": 0},
        ],
        "rating": {
            "rank": 677,
            "total": 2517,
            "score": 7.6,
        },
    }


@pytest.mark.asyncio
async def test_render_subject_card_pillow_returns_base64() -> None:
    renderer = SubjectRenderer(render_mode="pillow")

    base64_image = await renderer.render_subject_card(build_subject_data())

    assert base64_image is not None
    assert len(base64_image) > 100
    assert base64.b64decode(base64_image).startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.asyncio
async def test_render_subject_card_pillow_with_failed_image_still_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = SubjectRenderer(render_mode="pillow")
    subject_data = build_subject_data()
    subject_data["image_url"] = "https://example.invalid/cover.png"

    monkeypatch.setattr(
        "src.render.subject_renderer.load_image_source",
        AsyncMock(return_value=None),
    )

    base64_image = await renderer.render_subject_card(subject_data)

    assert base64_image is not None
    assert base64.b64decode(base64_image).startswith(b"\x89PNG\r\n\x1a\n")
