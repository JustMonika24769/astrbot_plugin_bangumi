import base64
import io
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from astrbot_plugin_bangumi.src.domain import EPISODE_CARD_VARIANTS
from astrbot_plugin_bangumi.src.render import SubjectRenderer
from astrbot_plugin_bangumi.src.render.subject_renderer import _SUBJECT_CARD_STYLES
from astrbot_plugin_bangumi.tests.render.image_assertions import assert_png_image

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
            "count": {
                "1": 6,
                "2": 3,
                "3": 7,
                "4": 13,
                "5": 40,
                "6": 167,
                "7": 753,
                "8": 1234,
                "9": 194,
                "10": 100,
            },
            "score": 7.6,
        },
    }


@pytest.mark.asyncio
async def test_render_subject_card_pillow_returns_base64() -> None:
    renderer = SubjectRenderer(render_mode="pillow")

    base64_image = await renderer.render_subject_card(build_subject_data())

    assert base64_image is not None
    assert_png_image(base64_image, (2400, 1674), require_non_blank=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", EPISODE_CARD_VARIANTS)
async def test_render_subject_card_pillow_renders_all_named_variants(
    variant: str,
) -> None:
    renderer = SubjectRenderer(render_mode="pillow")

    base64_image = await renderer.render_subject_card(
        build_subject_data(), variant=variant
    )

    assert base64_image is not None
    assert_png_image(base64_image, (2400, 1674), require_non_blank=True)


@pytest.mark.asyncio
async def test_render_subject_card_default_variant_matches_cinematic() -> None:
    renderer = SubjectRenderer(render_mode="pillow")

    default_image = await renderer.render_subject_card(build_subject_data())
    cinematic_image = await renderer.render_subject_card(
        build_subject_data(), variant="cinematic_poster"
    )

    assert default_image == cinematic_image


@pytest.mark.asyncio
async def test_render_subject_card_variants_are_visually_distinct() -> None:
    renderer = SubjectRenderer(render_mode="pillow")

    fingerprints: set[tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]] = set()
    for variant in EPISODE_CARD_VARIANTS:
        payload = await renderer.render_subject_card(
            build_subject_data(), variant=variant
        )
        assert payload is not None
        image = Image.open(io.BytesIO(base64.b64decode(payload))).convert("RGBA")
        fingerprints.add(
            (
                image.getpixel((120, 96)),
                image.getpixel((2300, 80)),
                image.getpixel((1120, 360)),
            )
        )

    assert len(fingerprints) == len(EPISODE_CARD_VARIANTS)


@pytest.mark.asyncio
async def test_render_subject_card_weekday_badge_is_square() -> None:
    renderer = SubjectRenderer(render_mode="pillow")

    payload = await renderer.render_subject_card(
        build_subject_data(), variant="cinematic_poster"
    )

    assert payload is not None
    image = Image.open(io.BytesIO(base64.b64decode(payload))).convert("RGBA")
    accent = _SUBJECT_CARD_STYLES["cinematic_poster"].accent
    coords = [
        (x, y)
        for y in range(0, 220)
        for x in range(2180, 2400)
        if image.getpixel((x, y)) == accent
    ]
    assert coords
    left = min(x for x, _ in coords)
    top = min(y for _, y in coords)
    right = max(x for x, _ in coords)
    bottom = max(y for _, y in coords)

    badge_width = right - left + 1
    badge_height = bottom - top + 1
    assert 168 <= badge_width <= 172
    assert 168 <= badge_height <= 172
    assert abs(badge_width - badge_height) <= 2


@pytest.mark.asyncio
async def test_render_subject_card_pillow_includes_collection_badge() -> None:
    renderer = SubjectRenderer(render_mode="pillow")
    subject_data = build_subject_data()
    subject_data["collection"] = {"doing": 7805}

    base64_image = await renderer.render_subject_card(subject_data)

    assert base64_image is not None
    assert_png_image(base64_image, (2400, 1674), require_non_blank=True)


@pytest.mark.asyncio
async def test_render_subject_card_pillow_grows_for_full_episode_grid() -> None:
    renderer = SubjectRenderer(render_mode="pillow")
    subject_data = build_subject_data()
    subject_data["total_episodes"] = 13
    subject_data["episodes"] = [
        {
            "ep": episode_number,
            "type": 0,
            "airdate": f"2026-01-{episode_number:02d}",
            "comment": 1,
        }
        for episode_number in range(1, 14)
    ]

    base64_image = await renderer.render_subject_card(subject_data)

    assert base64_image is not None
    assert_png_image(base64_image, (2400, 1866), require_non_blank=True)


@pytest.mark.asyncio
async def test_render_subject_card_pillow_caps_long_episode_grid() -> None:
    renderer = SubjectRenderer(render_mode="pillow")
    subject_data = build_subject_data()
    subject_data["total_episodes"] = 60
    subject_data["episodes"] = [
        {
            "ep": episode_number,
            "type": 0,
            "airdate": f"2026-01-{min(episode_number, 28):02d}",
            "comment": 1,
        }
        for episode_number in range(1, 61)
    ]

    base64_image = await renderer.render_subject_card(subject_data)

    assert base64_image is not None
    assert_png_image(base64_image, (2400, 1866), require_non_blank=True)


@pytest.mark.asyncio
async def test_render_subject_card_pillow_with_failed_image_still_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = SubjectRenderer(render_mode="pillow")
    subject_data = build_subject_data()
    subject_data["image_url"] = "https://example.invalid/cover.png"

    monkeypatch.setattr(
        "astrbot_plugin_bangumi.src.render.subject_renderer.load_image_source",
        AsyncMock(return_value=None),
    )

    base64_image = await renderer.render_subject_card(subject_data)

    assert base64_image is not None
    assert_png_image(base64_image, (2400, 1674), require_non_blank=True)
