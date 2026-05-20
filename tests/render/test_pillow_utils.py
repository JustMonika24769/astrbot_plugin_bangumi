import base64
import io
import zipfile
from pathlib import Path

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


def test_smiley_sans_download_skips_existing_local_font(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    font_dir = tmp_path / "fonts"
    font_dir.mkdir()
    (font_dir / "SmileySans-Oblique.otf").write_bytes(b"font")

    def fail_urlopen(*args: object, **kwargs: object) -> object:
        raise AssertionError("existing Smiley Sans should not trigger network")

    monkeypatch.setattr(pillow_utils, "urlopen", fail_urlopen)

    assert not pillow_utils._download_smiley_sans(font_dir)


def test_smiley_sans_download_extracts_font(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("SmileySans-Oblique.otf", b"font-bytes")
    archive_bytes = archive.getvalue()

    class FakeResponse:
        def __init__(self, payload: bytes) -> None:
            self._buffer = io.BytesIO(payload)

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            return self._buffer.read(size)

    monkeypatch.setattr(
        pillow_utils,
        "urlopen",
        lambda *args, **kwargs: FakeResponse(archive_bytes),
    )

    assert pillow_utils._download_smiley_sans(tmp_path)
    assert (tmp_path / "SmileySans-Oblique.otf").read_bytes() == b"font-bytes"


def test_smiley_sans_download_failure_keeps_fallback_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pillow_utils,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")),
    )

    assert not pillow_utils._download_smiley_sans(tmp_path)
    assert not (tmp_path / "SmileySans-Oblique.otf.tmp").exists()
    assert get_font(18) is not None


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
