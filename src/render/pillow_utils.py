import asyncio
import base64
import io
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from astrbot.api import logger
from PIL import (
    Image,
    ImageDraw,
    ImageFilter,
    ImageFont,
    ImageOps,
    UnidentifiedImageError,
)

RGBColor = tuple[int, int, int]
RGBAColor = tuple[int, int, int, int]
FontType = ImageFont.FreeTypeFont | ImageFont.ImageFont
Rect = tuple[int, int, int, int]

_DATA_URI_PATTERN = re.compile(r"^data:image/[^;]+;base64,(?P<data>.+)$", re.DOTALL)
_REGULAR_FONT_PATHS = (
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("C:/Windows/Fonts/msyh.ttc"),
)
_BOLD_FONT_PATHS = (
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/msyh.ttc"),
)


@lru_cache(maxsize=64)
def get_font(size: int, *, bold: bool = False) -> FontType:
    candidates = _BOLD_FONT_PATHS if bold else _REGULAR_FONT_PATHS
    for path in candidates:
        if not path.exists():
            continue
        try:
            return ImageFont.truetype(str(path), size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def image_to_base64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def measure_text(draw: ImageDraw.ImageDraw, text: str, font: FontType) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return int(right - left), int(bottom - top)


def line_height(draw: ImageDraw.ImageDraw, font: FontType) -> int:
    return measure_text(draw, "Hg国", font)[1]


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: FontType,
    max_width: int,
    max_lines: int,
) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.replace("\r", " ").replace("\n", " ")).strip()
    if not normalized:
        return []

    lines: list[str] = []
    current = ""
    truncated = False

    for char in normalized:
        candidate = f"{current}{char}"
        if current and measure_text(draw, candidate, font)[0] > max_width:
            lines.append(current)
            current = char
            if len(lines) >= max_lines:
                truncated = True
                break
        else:
            current = candidate

    if not truncated and current:
        lines.append(current)
        if len(lines) > max_lines:
            truncated = True
            lines = lines[:max_lines]

    if truncated and lines:
        lines[-1] = ellipsize_text(draw, lines[-1], font, max_width)

    return lines[:max_lines]


def ellipsize_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: FontType,
    max_width: int,
) -> str:
    if measure_text(draw, text, font)[0] <= max_width:
        return text

    ellipsis = "..."
    candidate = text
    while candidate:
        candidate = candidate[:-1]
        merged = f"{candidate}{ellipsis}"
        if measure_text(draw, merged, font)[0] <= max_width:
            return merged
    return ellipsis


def draw_text_block(
    draw: ImageDraw.ImageDraw,
    box: Rect,
    text: str,
    font: FontType,
    fill: RGBColor | RGBAColor,
    *,
    max_lines: int,
    line_spacing: int = 8,
) -> int:
    lines = wrap_text(draw, text, font, box[2] - box[0], max_lines)
    text_line_height = line_height(draw, font)
    current_y = box[1]

    for line in lines:
        draw.text((box[0], current_y), line, font=font, fill=fill)
        current_y += text_line_height + line_spacing

    if not lines:
        return 0
    return current_y - box[1] - line_spacing


def draw_pill(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: FontType,
    *,
    fill: RGBColor | RGBAColor,
    text_fill: RGBColor | RGBAColor,
    padding_x: int = 16,
    padding_y: int = 9,
    outline: RGBColor | RGBAColor | None = None,
) -> int:
    text_width, text_height = measure_text(draw, text, font)
    pill_width = text_width + padding_x * 2
    pill_height = text_height + padding_y * 2
    radius = pill_height // 2
    rect = (xy[0], xy[1], xy[0] + pill_width, xy[1] + pill_height)
    draw.rounded_rectangle(rect, radius=radius, fill=fill, outline=outline, width=1)
    draw.text((xy[0] + padding_x, xy[1] + padding_y - 1), text, font=font, fill=text_fill)
    return pill_width


def create_linear_gradient(
    size: tuple[int, int],
    start: RGBColor,
    end: RGBColor,
) -> Image.Image:
    _, height = size
    image = Image.new("RGBA", size)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        red = int(start[0] + (end[0] - start[0]) * ratio)
        green = int(start[1] + (end[1] - start[1]) * ratio)
        blue = int(start[2] + (end[2] - start[2]) * ratio)
        draw.line((0, y, size[0], y), fill=(red, green, blue, 255))
    return image


def blend_color(color: RGBColor, amount: float, target: RGBColor) -> RGBColor:
    clamped = max(0.0, min(1.0, amount))
    return (
        int(color[0] + (target[0] - color[0]) * clamped),
        int(color[1] + (target[1] - color[1]) * clamped),
        int(color[2] + (target[2] - color[2]) * clamped),
    )


def get_image_accent(image: Image.Image | None) -> RGBColor:
    if image is None:
        return (60, 98, 118)
    reduced = image.convert("RGB").resize((1, 1), Image.Resampling.BILINEAR)
    color = reduced.getpixel((0, 0))
    if not isinstance(color, tuple) or len(color) < 3:
        return (60, 98, 118)
    return blend_color(
        (int(color[0]), int(color[1]), int(color[2])),
        0.35,
        (76, 105, 122),
    )


def create_placeholder_image(
    size: tuple[int, int],
    title: str,
    accent: RGBColor,
) -> Image.Image:
    base = create_linear_gradient(
        size,
        blend_color(accent, 0.7, (245, 247, 250)),
        blend_color(accent, 0.1, (24, 34, 44)),
    )
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = size
    draw.ellipse(
        (-width // 5, height // 3, width // 2, height + height // 3),
        fill=(*blend_color(accent, 0.55, (255, 255, 255)), 120),
    )
    draw.ellipse(
        (width // 2, -height // 6, width + width // 5, height // 2),
        fill=(*blend_color(accent, 0.25, (18, 24, 34)), 120),
    )
    base.alpha_composite(overlay)
    base_draw = ImageDraw.Draw(base)

    glyph = title.strip()[:1] or "B"
    glyph_font = get_font(max(48, min(size) // 3), bold=True)
    text_width, text_height = measure_text(base_draw, glyph, glyph_font)
    base_draw.text(
        ((width - text_width) // 2, (height - text_height) // 2 - 18),
        glyph,
        font=glyph_font,
        fill=(255, 255, 255, 210),
    )
    return base


def add_shadow(
    canvas: Image.Image,
    box: Rect,
    *,
    radius: int,
    blur: int = 24,
    offset: tuple[int, int] = (0, 12),
    shadow_color: RGBAColor = (15, 23, 42, 46),
) -> None:
    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow_layer)
    shadow_box = (
        box[0] + offset[0],
        box[1] + offset[1],
        box[2] + offset[0],
        box[3] + offset[1],
    )
    draw.rounded_rectangle(shadow_box, radius=radius, fill=shadow_color)
    blurred = shadow_layer.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(blurred)


def round_image(image: Image.Image, radius: int) -> Image.Image:
    rounded = image.convert("RGBA")
    mask = Image.new("L", rounded.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, rounded.width, rounded.height), radius=radius, fill=255)
    rounded.putalpha(mask)
    return rounded


def fit_cover(image: Image.Image, size: tuple[int, int], radius: int) -> Image.Image:
    fitted = ImageOps.fit(image.convert("RGBA"), size, method=Image.Resampling.LANCZOS)
    return round_image(fitted, radius)


def open_image_from_bytes(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGBA")


async def load_image_source(
    source: str | None,
    session: aiohttp.ClientSession | None = None,
) -> Image.Image | None:
    if not source:
        return None

    match = _DATA_URI_PATTERN.match(source)
    if match:
        try:
            image_bytes = base64.b64decode(match.group("data"), validate=False)
            return await asyncio.to_thread(open_image_from_bytes, image_bytes)
        except (ValueError, OSError, UnidentifiedImageError) as e:
            logger.warning(f"[+] 解析 data URI 图片失败: {e}")
            return None

    parsed = urlparse(source)
    if parsed.scheme not in {"http", "https"}:
        return None

    client_timeout = aiohttp.ClientTimeout(total=10)

    try:
        if session and not session.closed:
            async with session.get(source, timeout=client_timeout) as response:
                if response.status != 200:
                    logger.warning(
                        f"[+] 图片下载失败,状态码: {response.status}, url={source}"
                    )
                    return None
                image_bytes = await response.read()
                return await asyncio.to_thread(open_image_from_bytes, image_bytes)

        async with (
            aiohttp.ClientSession() as temp_session,
            temp_session.get(source, timeout=client_timeout) as response,
        ):
            if response.status != 200:
                logger.warning(
                    f"[+] 图片下载失败,状态码: {response.status}, url={source}"
                )
                return None
            image_bytes = await response.read()
            return await asyncio.to_thread(open_image_from_bytes, image_bytes)
    except (
        aiohttp.ClientError,
        TimeoutError,
        OSError,
        UnidentifiedImageError,
        ValueError,
    ) as e:
        logger.warning(f"[+] 加载图片失败, url={source}, error={e}")
        return None
