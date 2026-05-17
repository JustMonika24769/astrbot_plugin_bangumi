import asyncio
from typing import cast

from astrbot.api import logger
from PIL import Image, ImageDraw

from ..domain.contracts import RenderData
from ..domain.schemas import Episode
from .base_renderer import BaseRenderer
from .pillow_utils import (
    create_placeholder_image,
    draw_text_block,
    fit_cover,
    get_font,
    get_image_accent,
    image_to_base64,
    load_image_source,
    measure_text,
    wrap_text,
)
from .pillow_utils import (
    stringify_value as _stringify_value,
)


def _extract_episode_titles(data: RenderData) -> tuple[str, str]:
    primary = _stringify_value(data.get("name_cn")) or _stringify_value(
        data.get("name")
    )
    secondary = _stringify_value(data.get("name"))
    if not primary:
        primary = "更新内容待补充"
    if secondary == primary:
        secondary = ""
    return primary, secondary


def _format_duration_label(data: RenderData) -> str:
    existing_label = _stringify_value(data.get("duration_label"))
    if existing_label:
        return existing_label

    duration_text = _stringify_value(data.get("duration"))
    if ":" in duration_text:
        parts = duration_text.split(":")
        if len(parts) >= 3:
            hours = int(parts[0]) if parts[0].isdigit() else 0
            minutes = int(parts[1]) if parts[1].isdigit() else 0
            return f"{hours * 60 + minutes}min"
        if parts[0].isdigit():
            return f"{int(parts[0])}min"
    if duration_text.endswith("min"):
        return duration_text

    duration_seconds = data.get("duration_seconds")
    if isinstance(duration_seconds, int) and duration_seconds > 0:
        return f"{max(1, round(duration_seconds / 60))}min"
    return "24min"


def _draw_episode_card_image(
    render_data: RenderData,
    cover_image: Image.Image | None,
) -> str:
    width, height = 2304, 3072
    primary_title, _secondary_title = _extract_episode_titles(render_data)
    accent = get_image_accent(cover_image)

    cover = cover_image
    if cover is None:
        canvas = Image.new("RGBA", (width, height), (9, 9, 11, 255))
        fallback = create_placeholder_image((width, height), primary_title, accent)
        canvas.alpha_composite(fallback)
        draw = ImageDraw.Draw(canvas)
        icon_font = get_font(260, bold=True)
        icon = "🎬"
        icon_width, icon_height = measure_text(draw, icon, icon_font)
        draw.text(
            ((width - icon_width) // 2, (height - icon_height) // 2 - 420),
            icon,
            font=icon_font,
            fill=(36, 36, 39, 255),
        )
    else:
        canvas = fit_cover(cover, (width, height), 0)
        if canvas.mode != "RGBA":
            canvas = canvas.convert("RGBA")

    gradient = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gradient_draw = ImageDraw.Draw(gradient)
    gradient_start = int(height * 0.4)
    for y in range(gradient_start, height):
        ratio = (y - gradient_start) / max(height - gradient_start - 1, 1)
        if ratio < 0.3:
            alpha = int(76 * (ratio / 0.3))
        elif ratio < 0.6:
            alpha = int(76 + (178 - 76) * ((ratio - 0.3) / 0.3))
        else:
            alpha = int(178 + (242 - 178) * ((ratio - 0.6) / 0.4))
        gradient_draw.line((0, y, width, y), fill=(0, 0, 0, alpha))
    canvas.alpha_composite(gradient)
    draw = ImageDraw.Draw(canvas)

    episode_number = render_data.get("ep")
    sort_number = render_data.get("sort")
    number_source = sort_number if sort_number not in (None, "") else episode_number
    episode_label = "EP.01"
    if isinstance(episode_number, int):
        episode_label = f"EP.{episode_number:02d}"
    if isinstance(number_source, int):
        episode_label = f"EP.{number_source:02d}"
    elif isinstance(number_source, str) and number_source.isdigit():
        episode_label = f"EP.{int(number_source):02d}"

    ep_font = get_font(168, bold=True)
    title_font = get_font(144, bold=True)
    meta_font = get_font(51, bold=True)
    desc_font = get_font(51)

    left = 84
    right = 84
    content_top_padding = 96
    content_bottom_padding = 84
    title_row_height = 174
    title_row_margin_bottom = 36
    metadata_height = 78
    metadata_margin_bottom = 60
    description_line_step = 87
    description_margin_bottom = 72

    description = _stringify_value(render_data.get("desc"))
    description_lines = wrap_text(
        draw,
        description,
        desc_font,
        width - left - right,
        3,
    )
    description_height = len(description_lines) * description_line_step
    description_block_height = (
        description_height + description_margin_bottom if description_lines else 0
    )
    content_height = (
        content_top_padding
        + title_row_height
        + title_row_margin_bottom
        + metadata_height
        + metadata_margin_bottom
        + description_block_height
        + content_bottom_padding
    )
    header_y = height - content_height + content_top_padding

    ep_width, _ = measure_text(draw, episode_label, ep_font)
    draw.text((left, header_y), episode_label, font=ep_font, fill=(236, 72, 153, 255))
    title_x = left + ep_width + 21
    draw_text_block(
        draw,
        (title_x, header_y + 15, width - right, header_y + title_row_height),
        primary_title,
        title_font,
        (255, 255, 255, 255),
        max_lines=1,
        line_spacing=0,
    )
    airdate = _stringify_value(render_data.get("airdate"))
    year = airdate.split("-", 1)[0] if "-" in airdate else airdate
    if not year:
        year = "2026"
    duration = _stringify_value(
        render_data.get("duration_label")
    ) or _format_duration_label(render_data)
    comment = render_data.get("comment")
    metadata = [year, duration]
    if isinstance(comment, int) and comment > 0:
        metadata.append(f"{comment} comments")
    meta_text = "   |   ".join(metadata)
    metadata_y = header_y + title_row_height + title_row_margin_bottom
    draw.text((left, metadata_y), meta_text, font=meta_font, fill=(204, 204, 204, 255))

    if description_lines:
        description_y = metadata_y + metadata_height + metadata_margin_bottom
        draw_text_block(
            draw,
            (left, description_y, width - right, height - content_bottom_padding),
            description,
            desc_font,
            (216, 216, 216, 255),
            max_lines=3,
            line_spacing=34,
        )

    return image_to_base64(canvas)


class EpisodeRenderer(BaseRenderer):
    async def _render_episode_pillow(self, render_data: RenderData) -> str:
        image_url = _stringify_value(render_data.get("image_url"))
        cover_image = await load_image_source(image_url, self._session)
        return await asyncio.to_thread(
            _draw_episode_card_image, render_data, cover_image
        )

    async def _render_episode_pillow_with_placeholder(
        self, render_data: RenderData
    ) -> str:
        try:
            return await self._render_episode_pillow(render_data)
        except Exception as e:
            logger.warning(f"[+] Pillow 单集卡片渲染失败,使用纯 PIL 退避卡片: {e}")
            fallback_data = render_data.copy()
            fallback_data["image_url"] = ""
            return await asyncio.to_thread(
                _draw_episode_card_image,
                fallback_data,
                None,
            )

    async def render_episode(
        self,
        episode_data: Episode,
        rpc_url: str | None = None,
        headless: bool = True,
        max_retries: int = 3,
    ) -> str | None:
        """
        渲染单集信息卡片并返回 Base64 编码的图片字符串
        """
        render_data = cast(RenderData, episode_data.model_dump())
        render_data["duration_label"] = _format_duration_label(render_data)

        if self.render_mode == "pillow":
            return await self._render_episode_pillow_with_placeholder(render_data)

        return await self.render(
            template_path="update/episode.html",
            render_data=render_data,
            selector="#card-container",
            rpc_url=rpc_url,
            headless=headless,
            max_retries=max_retries,
            pillow_fallback=lambda: self._render_episode_pillow_with_placeholder(
                render_data
            ),
        )
