import base64
import io

import pytest
from PIL import Image, ImageDraw

from astrbot_plugin_bangumi.src.render import pillow_utils
from astrbot_plugin_bangumi.src.render.pillow_utils import (
    create_placeholder_image,
    ellipsize_text,
    get_font,
    is_visually_blank,
    load_image_source,
    measure_text,
    wrap_text,
)


def test_is_visually_blank_detects_white_and_transparent_images() -> None:
    assert is_visually_blank(Image.new("RGBA", (10, 10), (255, 255, 255, 255)))
    assert is_visually_blank(Image.new("RGBA", (10, 10), (0, 0, 0, 0)))
    assert not is_visually_blank(Image.new("RGBA", (10, 10), (80, 120, 140, 255)))


def test_wrap_text_breaks_long_labels_into_multiple_lines() -> None:
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    font = get_font(24)
    text = "This renderer needs predictable wrapping behavior across long labels."

    lines = wrap_text(draw, text, font, max_width=140, max_lines=2)

    assert len(lines) >= 2
    assert all(measure_text(draw, line, font)[0] <= 140 for line in lines)
    assert all(line for line in lines)


def test_ellipsize_text_shortens_overlong_copy() -> None:
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    font = get_font(24)
    text = "ThisLabelIsDefinitelyTooLongForTheBox"

    result = ellipsize_text(draw, text, font, max_width=120)

    assert result.endswith("...")
    assert result != text
    assert measure_text(draw, result, font)[0] <= 120


def test_create_placeholder_image_is_non_blank_and_sized() -> None:
    image = create_placeholder_image((160, 240), "Placeholder", (60, 98, 118))

    assert image.size == (160, 240)
    assert image.mode == "RGBA"
    assert not is_visually_blank(image)


@pytest.mark.asyncio
async def test_load_image_source_accepts_data_uri() -> None:
    image = Image.new("RGBA", (2, 2), (80, 120, 140, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    source = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()

    loaded = await load_image_source(source)

    assert loaded is not None
    assert loaded.size == (2, 2)


@pytest.mark.asyncio
async def test_load_image_source_rejects_non_http_source() -> None:
    assert await load_image_source("file:///tmp/cover.png") is None


@pytest.mark.asyncio
async def test_load_image_source_rejects_oversized_data_uri(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pillow_utils, "_MAX_IMAGE_BYTES", 3)
    source = "data:image/png;base64," + base64.b64encode(b"1234").decode()

    assert await load_image_source(source) is None
