import asyncio
from typing import cast

from astrbot.api import logger
from PIL import Image, ImageDraw

from ..services import Episode, RenderData
from .base_renderer import BaseRenderer
from .pillow_utils import (
    add_shadow,
    blend_color,
    create_linear_gradient,
    create_placeholder_image,
    draw_pill,
    draw_text_block,
    fit_cover,
    get_font,
    get_image_accent,
    image_to_base64,
    load_image_source,
)


def _stringify_value(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _extract_episode_titles(data: RenderData) -> tuple[str, str]:
    primary = _stringify_value(data.get("name_cn")) or _stringify_value(data.get("name"))
    secondary = _stringify_value(data.get("name"))
    if not primary:
        primary = "更新内容待补充"
    if secondary == primary:
        secondary = ""
    return primary, secondary


def _draw_episode_card_image(
    render_data: RenderData,
    cover_image: Image.Image | None,
) -> str:
    width, height = 1100, 420
    primary_title, secondary_title = _extract_episode_titles(render_data)
    accent = get_image_accent(cover_image)

    canvas = create_linear_gradient(
        (width, height),
        blend_color(accent, 0.86, (244, 246, 248)),
        blend_color(accent, 0.62, (225, 232, 236)),
    )
    background_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(background_overlay)
    overlay_draw.ellipse(
        (730, -90, 1190, 250),
        fill=(*blend_color(accent, 0.72, (255, 255, 255)), 110),
    )
    overlay_draw.ellipse(
        (760, 210, 1200, 560),
        fill=(*blend_color(accent, 0.34, (255, 255, 255)), 82),
    )
    canvas.alpha_composite(background_overlay)

    card_box = (32, 32, 1068, 388)
    add_shadow(canvas, card_box, radius=34, blur=26)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        card_box,
        radius=34,
        fill=(251, 252, 254, 248),
        outline=(221, 228, 234, 255),
        width=1,
    )

    cover = cover_image or create_placeholder_image((230, 316), primary_title, accent)
    cover_card = fit_cover(cover, (230, 316), 24)
    cover_box = (70, 52, 300, 368)
    add_shadow(
        canvas,
        cover_box,
        radius=24,
        blur=20,
        offset=(0, 10),
        shadow_color=(15, 23, 42, 36),
    )
    canvas.alpha_composite(cover_card, (cover_box[0], cover_box[1]))
    draw = ImageDraw.Draw(canvas)

    badge_font = get_font(20, bold=True)
    title_font = get_font(40, bold=True)
    secondary_font = get_font(24)
    episode_font = get_font(44, bold=True)
    meta_font = get_font(19, bold=True)
    body_font = get_font(20)

    draw_pill(
        draw,
        (340, 74),
        "更新提醒",
        badge_font,
        fill=(255, 242, 225, 255),
        text_fill=(163, 96, 32),
        outline=(244, 214, 180, 255),
    )

    airdate = _stringify_value(render_data.get("airdate"))
    duration = _stringify_value(render_data.get("duration"))
    comment = render_data.get("comment")
    meta_x = 462
    if airdate:
        meta_x += draw_pill(
            draw,
            (meta_x, 74),
            f"播出 {airdate}",
            meta_font,
            fill=(241, 245, 248, 255),
            text_fill=(73, 83, 93),
            outline=(223, 228, 235, 255),
        ) + 10
    if duration:
        meta_x += draw_pill(
            draw,
            (meta_x, 74),
            duration,
            meta_font,
            fill=(241, 245, 248, 255),
            text_fill=(73, 83, 93),
            outline=(223, 228, 235, 255),
        ) + 10
    if isinstance(comment, int) and comment > 0:
        draw_pill(
            draw,
            (meta_x, 74),
            f"讨论 {comment}",
            meta_font,
            fill=(241, 245, 248, 255),
            text_fill=(73, 83, 93),
            outline=(223, 228, 235, 255),
        )

    draw_text_block(
        draw,
        (340, 132, 1018, 236),
        primary_title,
        title_font,
        (16, 24, 33),
        max_lines=2,
        line_spacing=8,
    )
    if secondary_title:
        draw_text_block(
            draw,
            (340, 246, 1018, 282),
            secondary_title,
            secondary_font,
            (95, 107, 119),
            max_lines=1,
        )

    info_box = (340, 304, 1018, 358)
    draw.rounded_rectangle(
        info_box,
        radius=24,
        fill=(*blend_color(accent, 0.9, (248, 250, 252)), 255),
        outline=(*blend_color(accent, 0.5, (218, 226, 232)), 255),
        width=1,
    )

    episode_number = render_data.get("ep")
    episode_label = "EP --"
    if isinstance(episode_number, int):
        episode_label = f"EP {episode_number:02d}"
    elif isinstance(episode_number, str) and episode_number.isdigit():
        episode_label = f"EP {int(episode_number):02d}"
    draw.text((368, 315), episode_label, font=episode_font, fill=(18, 26, 35))

    name_label = secondary_title or primary_title
    draw_text_block(
        draw,
        (578, 318, 998, 350),
        f"标题 {name_label}",
        body_font,
        (79, 90, 101),
        max_lines=1,
    )

    return image_to_base64(canvas)


class EpisodeRenderer(BaseRenderer):
    async def _render_episode_pillow(self, render_data: RenderData) -> str:
        image_url = _stringify_value(render_data.get("image_url"))
        cover_image = await load_image_source(image_url, self._session)
        return await asyncio.to_thread(_draw_episode_card_image, render_data, cover_image)

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
        # 数据转换
        render_data = cast(RenderData, episode_data.model_dump())

        if self.render_mode == "pillow":
            try:
                return await self._render_episode_pillow(render_data)
            except Exception as e:
                logger.warning(f"[+] Pillow 单集卡片渲染失败,回退 HTML 渲染: {e}")

        return await self.render(
            template_path="update/episode.html",
            render_data=render_data,
            selector="#card-container",
            rpc_url=rpc_url,
            headless=headless,
            max_retries=max_retries,
        )
