import asyncio
import datetime
import re
from collections import Counter
from collections.abc import Mapping
from contextlib import suppress
from typing import cast

from astrbot.api import logger
from PIL import Image, ImageDraw

from ..bangumi_types import JsonValue
from ..services import EpisodeItem, RenderData, SubjectType
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
    measure_text,
)


def _process_images(data: RenderData) -> None:
    if "image_url" in data:
        return

    images = data.get("images")
    if not isinstance(images, dict):
        return

    image_map = cast(dict[str, object], images)
    for key in ("large", "common", "medium"):
        value = image_map.get(key)
        if isinstance(value, str):
            data["image_url"] = value
            return
    data["image_url"] = ""


def _process_dates(data: RenderData) -> None:
    if "date" in data:
        return
    if "air_date" in data:
        data["date"] = data["air_date"]


def _process_platform(data: RenderData) -> None:
    if "platform" in data:
        return
    if "type" not in data:
        return

    raw_type = data.get("type")
    if isinstance(raw_type, int):
        type_id = raw_type
    elif isinstance(raw_type, str):
        try:
            type_id = int(raw_type)
        except ValueError:
            data["platform"] = "未知"
            return
    else:
        data["platform"] = "未知"
        return

    try:
        data["platform"] = SubjectType(type_id).to_display()
    except ValueError:
        data["platform"] = "未知"


def _infer_air_weekday(aired_weekdays: list[int]) -> str:
    if not aired_weekdays:
        return ""

    weekday_names = {1: "月", 2: "火", 3: "水", 4: "木", 5: "金", 6: "土", 7: "日"}
    recent = aired_weekdays[-4:]
    most_common = Counter(recent).most_common(1)[0][0]
    return weekday_names.get(most_common, "")


def _parse_episode_list(
    episodes: list[EpisodeItem], today: datetime.date
) -> tuple[list[dict[str, int | bool | None]], list[int]]:
    episode_list: list[dict[str, int | bool | None]] = []
    aired_weekdays: list[int] = []

    for ep in episodes:
        if ep.get("type", 0) != 0 or ep.get("ep", 0) == 0:
            continue

        aired = False
        airdate_str = ep.get("airdate")
        if airdate_str:
            try:
                airdate = datetime.datetime.strptime(airdate_str, "%Y-%m-%d").date()
                aired = airdate <= today
                if aired:
                    aired_weekdays.append(airdate.isoweekday())
            except ValueError:
                pass

        if ep.get("comment", 0) > 0:
            aired = True

        episode_list.append({"ep": ep.get("ep"), "aired": aired})

    return episode_list, aired_weekdays


def _process_episodes(data: RenderData) -> None:
    episodes = data.get("episodes")
    if not isinstance(episodes, list):
        return

    today = datetime.date.today()
    normalized_episodes: list[EpisodeItem] = []
    for episode in episodes:
        if isinstance(episode, dict):
            normalized_episodes.append(cast(EpisodeItem, episode))
    episode_list, aired_weekdays = _parse_episode_list(normalized_episodes, today)
    data["episode_list"] = cast(JsonValue, episode_list)

    air_weekday = _infer_air_weekday(aired_weekdays)
    if air_weekday:
        data["air_weekday"] = air_weekday


def preprocess_data(data: RenderData) -> RenderData:
    processed = data.copy()
    _process_images(processed)
    _process_dates(processed)
    _process_platform(processed)
    _process_episodes(processed)
    return processed


def _stringify_value(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _extract_infobox_text(value: object) -> str:
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _extract_infobox_text(item)
            if text:
                parts.append(text)
        return " / ".join(parts)
    if isinstance(value, Mapping):
        if "v" in value:
            return _extract_infobox_text(value["v"])
        if "value" in value:
            return _extract_infobox_text(value["value"])
    return _stringify_value(value)


def _get_infobox_value(data: RenderData, key_name: str) -> str:
    infobox = data.get("infobox")
    if not isinstance(infobox, list):
        return ""

    for item in infobox:
        if not isinstance(item, Mapping):
            continue
        key = item.get("key")
        if isinstance(key, str) and key.strip() == key_name:
            return _extract_infobox_text(item.get("value"))
    return ""


def _extract_total_episodes(data: RenderData) -> int | None:
    for key in ("total_episodes", "eps"):
        raw_value = data.get(key)
        if isinstance(raw_value, int) and raw_value > 0:
            return raw_value
        if isinstance(raw_value, str):
            match = re.search(r"\d+", raw_value)
            if match:
                return int(match.group())

    infobox_value = _get_infobox_value(data, "话数")
    match = re.search(r"\d+", infobox_value)
    if match:
        return int(match.group())
    return None


def _extract_subject_titles(data: RenderData) -> tuple[str, str]:
    primary = _stringify_value(data.get("name_cn")) or _stringify_value(data.get("name"))
    secondary = _stringify_value(data.get("name"))
    if not primary:
        primary = "未知条目"
    if secondary == primary:
        secondary = ""
    return primary, secondary


def _extract_tags(data: RenderData, limit: int = 6) -> list[str]:
    raw_tags = data.get("tags")
    if not isinstance(raw_tags, list):
        return []

    tags: list[str] = []
    for tag in raw_tags:
        if not isinstance(tag, Mapping):
            continue
        name = tag.get("name")
        if isinstance(name, str) and name.strip():
            tags.append(name.strip())
        if len(tags) >= limit:
            break
    return tags


def _extract_rating_metrics(data: RenderData) -> tuple[str, str, str]:
    score_text = "--"
    rank_text = "--"
    total_text = "--"

    rating = data.get("rating")
    if not isinstance(rating, Mapping):
        return score_text, rank_text, total_text

    score = rating.get("score")
    if isinstance(score, (int, float)):
        score_text = f"{float(score):.1f}"
    elif isinstance(score, str):
        with suppress(ValueError):
            score_text = f"{float(score):.1f}"

    rank = rating.get("rank")
    if isinstance(rank, int) or (isinstance(rank, str) and rank.isdigit()):
        rank_text = f"#{rank}"

    total = rating.get("total")
    if isinstance(total, int):
        total_text = f"{total:,}"
    elif isinstance(total, str):
        with suppress(ValueError):
            total_text = f"{int(total):,}"

    return score_text, rank_text, total_text


def _build_subject_meta(data: RenderData) -> list[str]:
    meta_items: list[str] = []

    date_text = _stringify_value(data.get("date")) or _get_infobox_value(data, "放送开始")
    if date_text:
        meta_items.append(f"首播 {date_text}")

    platform = _stringify_value(data.get("platform"))
    if platform:
        meta_items.append(platform)

    total_episodes = _extract_total_episodes(data)
    if total_episodes:
        meta_items.append(f"全 {total_episodes} 话")

    return meta_items


def _build_progress_text(data: RenderData) -> str:
    parts: list[str] = []

    air_weekday = _stringify_value(data.get("air_weekday"))
    if air_weekday:
        parts.append(f"放送: 每周{air_weekday}")

    raw_episode_list = data.get("episode_list")
    if isinstance(raw_episode_list, list) and raw_episode_list:
        aired_count = 0
        total_count = 0
        for item in raw_episode_list:
            if not isinstance(item, Mapping):
                continue
            total_count += 1
            if item.get("aired") is True:
                aired_count += 1

        if total_count > 0:
            total_episodes = _extract_total_episodes(data) or total_count
            parts.append(f"已播: {aired_count}/{total_episodes}")

    return "  ·  ".join(parts)


def _build_subject_summary(data: RenderData) -> str:
    summary = _stringify_value(data.get("summary"))
    if not summary:
        return "暂无简介"
    return re.sub(r"\s+", " ", summary).strip()


def _draw_subject_card_image(
    data: RenderData,
    cover_image: Image.Image | None,
) -> str:
    width, height = 1200, 700
    primary_title, secondary_title = _extract_subject_titles(data)
    accent = get_image_accent(cover_image)

    canvas = create_linear_gradient(
        (width, height),
        (243, 246, 249),
        blend_color(accent, 0.82, (226, 233, 238)),
    )
    background_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(background_overlay)
    overlay_draw.ellipse(
        (760, -120, 1240, 280),
        fill=(*blend_color(accent, 0.7, (255, 255, 255)), 118),
    )
    overlay_draw.ellipse(
        (850, 430, 1320, 860),
        fill=(*blend_color(accent, 0.28, (255, 255, 255)), 78),
    )
    canvas.alpha_composite(background_overlay)

    card_box = (40, 40, 1160, 660)
    add_shadow(canvas, card_box, radius=38, blur=28)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        card_box,
        radius=38,
        fill=(251, 252, 254, 248),
        outline=(221, 228, 234, 255),
        width=1,
    )

    cover = cover_image or create_placeholder_image((320, 480), primary_title, accent)
    cover_card = fit_cover(cover, (320, 480), 30)
    cover_box = (82, 110, 402, 590)
    add_shadow(
        canvas,
        cover_box,
        radius=30,
        blur=22,
        offset=(0, 10),
        shadow_color=(15, 23, 42, 38),
    )
    canvas.alpha_composite(cover_card, (cover_box[0], cover_box[1]))
    draw = ImageDraw.Draw(canvas)

    badge_font = get_font(20, bold=True)
    title_font = get_font(48, bold=True)
    subtitle_font = get_font(26)
    meta_font = get_font(20, bold=True)
    stat_value_font = get_font(54, bold=True)
    stat_label_font = get_font(18)
    tag_font = get_font(20, bold=True)
    summary_font = get_font(25)
    footer_font = get_font(20, bold=True)

    right_x = 460
    draw_pill(
        draw,
        (right_x, 88),
        "Bangumi 条目",
        badge_font,
        fill=(*blend_color(accent, 0.82, (255, 255, 255)), 255),
        text_fill=blend_color(accent, 0.05, (18, 28, 39)),
        outline=(*blend_color(accent, 0.5, (210, 218, 226)), 255),
    )

    draw_text_block(
        draw,
        (right_x, 138, 1100, 246),
        primary_title,
        title_font,
        (16, 24, 33),
        max_lines=2,
        line_spacing=6,
    )
    if secondary_title:
        draw_text_block(
            draw,
            (right_x, 248, 1100, 286),
            secondary_title,
            subtitle_font,
            (95, 107, 119),
            max_lines=1,
        )

    meta_x = right_x
    for meta_item in _build_subject_meta(data):
        pill_width = draw_pill(
            draw,
            (meta_x, 300),
            meta_item,
            meta_font,
            fill=(241, 245, 248, 255),
            text_fill=(68, 80, 91),
            outline=(223, 229, 235, 255),
        )
        meta_x += pill_width + 12

    stats_box = (right_x, 350, 1108, 440)
    draw.rounded_rectangle(
        stats_box,
        radius=28,
        fill=(*blend_color(accent, 0.88, (248, 250, 252)), 255),
        outline=(*blend_color(accent, 0.5, (218, 226, 233)), 255),
        width=1,
    )
    score_text, rank_text, total_text = _extract_rating_metrics(data)
    stat_positions = (
        (486, "评分", score_text),
        (700, "排名", rank_text),
        (892, "评分人数", total_text),
    )
    for x_pos, label, value in stat_positions:
        draw.text((x_pos, 370), value, font=stat_value_font, fill=(18, 26, 35))
        draw.text((x_pos, 417), label, font=stat_label_font, fill=(101, 111, 121))

    tags = _extract_tags(data)
    tag_x = right_x
    tag_y = 470
    for tag in tags:
        preview_width = measure_text(draw, tag, tag_font)[0] + 32
        if tag_x + preview_width > 1090 and tag_y == 470:
            tag_x = right_x
            tag_y = 518
        pill_width = draw_pill(
            draw,
            (tag_x, tag_y),
            tag,
            tag_font,
            fill=(*blend_color(accent, 0.84, (255, 255, 255)), 255),
            text_fill=blend_color(accent, 0.1, (17, 29, 39)),
            outline=(*blend_color(accent, 0.5, (210, 221, 229)), 255),
        )
        tag_x += pill_width + 10

    summary_top = 530 if tag_y > 470 else 516
    draw.text(
        (right_x, summary_top),
        "简介",
        font=footer_font,
        fill=blend_color(accent, 0.08, (22, 33, 44)),
    )
    draw_text_block(
        draw,
        (right_x, summary_top + 38, 1100, 640),
        _build_subject_summary(data),
        summary_font,
        (73, 83, 94),
        max_lines=5,
        line_spacing=10,
    )

    progress_text = _build_progress_text(data)
    if progress_text:
        draw_pill(
            draw,
            (right_x, 612),
            progress_text,
            footer_font,
            fill=(*blend_color(accent, 0.12, (18, 28, 39)), 255),
            text_fill=(255, 255, 255, 255),
        )

    return image_to_base64(canvas)


class SubjectRenderer(BaseRenderer):
    async def _render_subject_card_pillow(self, render_data: RenderData) -> str:
        cover_source = _stringify_value(render_data.get("image_url"))
        cover_image = await load_image_source(cover_source, self._session)
        return await asyncio.to_thread(
            _draw_subject_card_image,
            render_data,
            cover_image,
        )

    async def render_subject_card(
        self,
        data: RenderData,
        rpc_url: str | None = None,
        headless: bool = True,
        wait_time: int = 0,
        max_retries: int = 3,
        timeout: int = 30000,
    ) -> str | None:
        render_data = preprocess_data(data)
        if self.render_mode == "pillow":
            try:
                return await self._render_subject_card_pillow(render_data)
            except Exception as e:
                logger.warning(f"[+] Pillow 条目卡片渲染失败,回退 HTML 渲染: {e}")

        return await self.render(
            template_path="subject/subject.html",
            render_data=render_data,
            selector="#card",
            sub_dir="subject",
            rpc_url=rpc_url,
            headless=headless,
            max_retries=max_retries,
            wait_time=wait_time,
            timeout=timeout,
        )

    async def render_batch_subject_cards_to_base64(
        self,
        data_list: list[RenderData],
        rpc_url: str | None = None,
        headless: bool = True,
        wait_time: int = 0,
        max_retries: int = 3,
        timeout: int = 30000,
        max_concurrency: int = 3,
    ) -> list[str]:
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _limited_render(data: RenderData) -> str | None:
            async with semaphore:
                return await self.render_subject_card(
                    data=data,
                    rpc_url=rpc_url,
                    headless=headless,
                    wait_time=wait_time,
                    max_retries=max_retries,
                    timeout=timeout,
                )

        tasks = [_limited_render(data) for data in data_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_results: list[str] = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.warning(f"批量渲染第 {i + 1} 项失败: {res}")
            elif isinstance(res, str) and res:
                valid_results.append(res)
        return valid_results
