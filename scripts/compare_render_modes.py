from __future__ import annotations

# ruff: noqa: E402
import argparse
import asyncio
import base64
import datetime as dt
import io
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import aiohttp
import numpy as np
from PIL import Image, ImageChops
from playwright.async_api import Page, async_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_PARENT = REPO_ROOT.parent
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))

from astrbot_plugin_bangumi.src.api import BangumiService
from astrbot_plugin_bangumi.src.render import (
    CalendarRenderer,
    EpisodeRenderer,
    SubjectRenderer,
)
from astrbot_plugin_bangumi.src.render.calendar_renderer import (
    reorder_days,
)
from astrbot_plugin_bangumi.src.render.subject_renderer import (
    preprocess_data,
)
from astrbot_plugin_bangumi.src.services.schemas import Episode

DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/"
    "x8AAwMCAO7+ZMsAAAAASUVORK5CYII="
)

SUBJECT_DATA: dict[str, Any] = {
    "date": "2026-01-11",
    "platform": "TV",
    "image_url": DATA_URI,
    "summary": (
        "总是活力充沛,却又很在意周遭目光的女孩与个性文静的男生,"
        "在校园生活中慢慢靠近彼此,是一部气质轻盈但情感推进很扎实的青春恋爱喜剧。"
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

EPISODE_DATA = Episode(
    airdate="2026-03-24",
    name="第5話 すれ違う気持ち",
    name_cn="第5话 擦肩而过的心意",
    duration="24:00",
    desc="两人在文化祭前夕重新审视彼此的距离。",
    ep=5,
    sort=5,
    id=1005,
    subject_id=525565,
    comment=18,
    type=0,
    disc=0,
    duration_seconds=1440,
    image_url=DATA_URI,
)

CALENDAR_DATA: list[dict[str, Any]] = [
    {
        "weekday": {"id": 1, "cn": "星期一", "en": "MON"},
        "items": [
            {
                "name": "正反対な君と僕",
                "name_cn": "相反的你和我",
                "images": {"common": DATA_URI, "large": DATA_URI, "medium": DATA_URI},
                "rating": {"score": 7.6},
                "rank": 677,
            },
            {
                "name": "Small Hours",
                "name_cn": "小小时光",
                "images": {"common": DATA_URI, "large": DATA_URI, "medium": DATA_URI},
                "rating": {"score": 7.1},
                "rank": 1204,
            },
        ],
    },
    {
        "weekday": {"id": 2, "cn": "星期二", "en": "TUE"},
        "items": [
            {
                "name": "夜明けのメロディ",
                "name_cn": "拂晓旋律",
                "images": {"common": DATA_URI, "large": DATA_URI, "medium": DATA_URI},
                "rating": {"score": 8.2},
                "rank": 214,
            }
        ],
    },
    {"weekday": {"id": 3, "cn": "星期三", "en": "WED"}, "items": []},
    {
        "weekday": {"id": 4, "cn": "星期四", "en": "THU"},
        "items": [
            {
                "name": "Orbit",
                "name_cn": "轨道",
                "images": {"common": DATA_URI, "large": DATA_URI, "medium": DATA_URI},
                "rating": {"score": 6.9},
                "rank": 1800,
            }
        ],
    },
    {"weekday": {"id": 5, "cn": "星期五", "en": "FRI"}, "items": []},
    {"weekday": {"id": 6, "cn": "星期六", "en": "SAT"}, "items": []},
    {"weekday": {"id": 7, "cn": "星期日", "en": "SUN"}, "items": []},
]

QUALITATIVE_NOTES = {
    "subject": [
        "HTML is an orange 800px flex card with episode grid and rating histogram.",
        "Pillow now renders the same DPR 3 orange card structure with cover, rating row, tags, summary, episode grid, rating histogram, and footer metadata.",
        "Remaining differences are primarily font metrics, glyph rasterization, and small shadow/antialiasing differences.",
    ],
    "episode": [
        "HTML is a vertical black poster card with pink episode typography.",
        "Pillow now renders the same DPR 3 vertical poster composition with cover/fallback, bottom gradient, EP label, metadata, and description.",
        "Remaining differences are primarily text rasterization and gradient interpolation.",
    ],
    "calendar": [
        "HTML is a seven-column grid with cover thumbnails, score, and rank.",
        "Pillow now renders the same DPR 3 seven-column weekday grid with today styling, cover thumbnails/placeholders, score, rank, and empty states.",
        "Remaining differences are primarily font metrics, rounded-corner antialiasing, and browser layout minutiae.",
    ],
}

SELECTORS = {
    "subject": "#card",
    "episode": "#card-container",
    "calendar": ".container",
}

DEFAULT_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
DEFAULT_USER_AGENT = (
    "AstrBot-Bangumi-Plugin/render-compare "
    "(https://github.com/united-pooh/astrbot_plugin_bangumi)"
)


@dataclass
class RenderDataset:
    source: str
    subject_data: dict[str, Any]
    episode_data: Episode
    calendar_data: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)


def fixture_dataset() -> RenderDataset:
    return RenderDataset(
        source="fixture",
        subject_data=dict(SUBJECT_DATA),
        episode_data=EPISODE_DATA,
        calendar_data=[dict(day) for day in CALENDAR_DATA],
        notes=["Using deterministic local fixture data."],
    )


def image_url_from_images(images: object) -> str:
    if not isinstance(images, dict):
        return ""
    for key in ("large", "common", "medium", "small", "grid"):
        value = images.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def limit_calendar_items(
    calendar_data: list[dict[str, Any]],
    item_limit: int | None,
) -> list[dict[str, Any]]:
    if item_limit is None:
        return calendar_data

    limited: list[dict[str, Any]] = []
    for day in calendar_data:
        day_copy = dict(day)
        items = day_copy.get("items")
        if isinstance(items, list):
            day_copy["items"] = items[:item_limit]
        limited.append(day_copy)
    return limited


def first_calendar_subject_id(calendar_data: list[dict[str, Any]]) -> str | None:
    for day in calendar_data:
        items = day.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            subject_id = item.get("id")
            if subject_id is not None:
                return str(subject_id)
    return None


def episode_from_raw_list(raw_episodes: list[dict[str, Any]]) -> Episode | None:
    parsed: list[Episode] = []
    for item in raw_episodes:
        try:
            parsed.append(Episode(**item))
        except (TypeError, ValueError):
            continue

    today = dt.date.today()
    normal_episodes = [
        episode for episode in parsed if episode.type == 0 and episode.ep > 0
    ]
    if not normal_episodes:
        return parsed[-1] if parsed else None

    aired: list[Episode] = []
    for episode in normal_episodes:
        if not episode.airdate:
            aired.append(episode)
            continue
        try:
            if dt.datetime.strptime(episode.airdate, "%Y-%m-%d").date() <= today:
                aired.append(episode)
        except ValueError:
            aired.append(episode)
    return (aired or normal_episodes)[-1]


async def resolve_subject_id(
    service: BangumiService,
    calendar_data: list[dict[str, Any]],
    subject_id: str | None,
    subject_query: str | None,
) -> str:
    if subject_id:
        return subject_id
    if subject_query:
        search_result = await service.search_subjects(subject_query, limit=1)
        items = search_result.get("data", [])
        if items and items[0].get("id") is not None:
            return str(items[0]["id"])
        raise RuntimeError(f"No Bangumi subject found for query: {subject_query}")

    calendar_subject_id = first_calendar_subject_id(calendar_data)
    if calendar_subject_id:
        return calendar_subject_id
    raise RuntimeError("No subject id found in live Bangumi calendar data.")


async def bangumi_dataset(args: argparse.Namespace) -> RenderDataset:
    access_token = args.access_token or os.getenv("BANGUMI_ACCESS_TOKEN", "")
    user_agent = args.user_agent or os.getenv("BANGUMI_USER_AGENT", DEFAULT_USER_AGENT)
    proxy = args.proxy or os.getenv("BANGUMI_PROXY") or None

    async with aiohttp.ClientSession() as session:
        service = BangumiService(
            access_token=access_token,
            user_agent=user_agent,
            proxy=proxy,
            max_retries=args.api_max_retries,
            session=session,
        )
        raw_calendar = await service.get_calendar()
        calendar_data = limit_calendar_items(
            [dict(day) for day in raw_calendar],
            args.calendar_item_limit,
        )

        subject_id = await resolve_subject_id(
            service,
            calendar_data,
            args.subject_id,
            args.subject_query,
        )
        subject_data = dict(await service.get_subject_details(subject_id))
        episode_response = await service.get_subject_episodes(int(subject_id))
        raw_episodes = [
            cast(dict[str, Any], item)
            for item in episode_response.get("data", [])
            if isinstance(item, dict)
        ]
        if raw_episodes:
            subject_data["episodes"] = raw_episodes
        if "total_episodes" not in subject_data and "eps" in subject_data:
            subject_data["total_episodes"] = subject_data["eps"]

        image_url = image_url_from_images(subject_data.get("images"))
        if image_url and not subject_data.get("image_url"):
            subject_data["image_url"] = image_url

        episode = episode_from_raw_list(raw_episodes)
        if episode is None:
            subject_name = str(
                subject_data.get("name_cn")
                or subject_data.get("name")
                or "真实数据条目"
            )
            episode = Episode(
                airdate=str(subject_data.get("date") or ""),
                name=subject_name,
                name_cn=subject_name,
                duration="24:00",
                desc=str(subject_data.get("summary") or ""),
                ep=1,
                sort=1,
                id=0,
                subject_id=int(subject_id),
                comment=0,
                type=0,
                disc=0,
                duration_seconds=1440,
            )

        if image_url:
            episode = episode.model_copy(update={"image_url": image_url})

    calendar_note = "full live calendar"
    if args.calendar_item_limit is not None:
        calendar_note = (
            f"live calendar capped to {args.calendar_item_limit} item(s) per day"
        )

    return RenderDataset(
        source="bangumi",
        subject_data=subject_data,
        episode_data=episode,
        calendar_data=calendar_data,
        notes=[
            f"Bangumi API subject_id: {subject_id}",
            f"Bangumi API calendar mode: {calendar_note}",
            f"Bangumi API subject title: {subject_data.get('name_cn') or subject_data.get('name') or 'unknown'}",
        ],
    )


async def load_dataset(args: argparse.Namespace) -> RenderDataset:
    if args.data_source == "fixture":
        return fixture_dataset()
    return await bangumi_dataset(args)


def decode_base64_png(payload: str) -> Image.Image:
    png_bytes = base64.b64decode(payload, validate=True)
    with Image.open(io.BytesIO(png_bytes)) as image:
        image.load()
        return image.convert("RGBA")


def image_metrics(image: Image.Image) -> dict[str, Any]:
    rgba = image.convert("RGBA")
    pixels = rgba.width * rgba.height
    alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
    return {
        "size": [rgba.width, rgba.height],
        "aspect_ratio": round(rgba.width / rgba.height, 6),
        "alpha_extrema": list(rgba.getchannel("A").getextrema()),
        "transparent_percent": round(
            float(np.count_nonzero(alpha == 0)) / pixels * 100, 6
        ),
        "translucent_percent": round(
            float(np.count_nonzero((alpha > 0) & (alpha < 255))) / pixels * 100,
            6,
        ),
        "opaque_percent": round(
            float(np.count_nonzero(alpha == 255)) / pixels * 100, 6
        ),
    }


def save_image(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def compare_images(
    name: str,
    html_image: Image.Image,
    pillow_image: Image.Image,
    output_dir: Path,
) -> dict[str, Any]:
    html_rgba = html_image.convert("RGBA")
    pillow_rgba = pillow_image.convert("RGBA")
    same_size = html_rgba.size == pillow_rgba.size
    aspect_delta = abs(
        html_rgba.width / html_rgba.height - pillow_rgba.width / pillow_rgba.height
    )

    if same_size:
        comparison_pillow = pillow_rgba
    else:
        comparison_pillow = pillow_rgba.resize(html_rgba.size, Image.Resampling.LANCZOS)

    diff = ImageChops.difference(html_rgba, comparison_pillow)
    diff_array = np.asarray(diff, dtype=np.float32)
    changed_mask = np.any(diff_array > 0, axis=2)
    significant_mask = np.any(diff_array[:, :, :3] > 8, axis=2) | (
        diff_array[:, :, 3] > 0
    )
    pixel_count = html_rgba.width * html_rgba.height
    mean_abs_rgba = diff_array.mean(axis=(0, 1))
    rms_rgba = np.sqrt(np.square(diff_array).mean(axis=(0, 1)))
    max_abs_rgba = diff_array.max(axis=(0, 1))

    diff_rgb = diff.convert("RGB").point(lambda value: min(255, value * 4))
    diff_visual = diff_rgb.convert("RGBA")
    diff_visual.putalpha(255)
    save_image(diff_visual, output_dir / f"{name}-normalized-diff.png")
    save_side_by_side(name, html_rgba, comparison_pillow, diff_visual, output_dir)

    return {
        "same_dimensions": same_size,
        "same_aspect_ratio": aspect_delta <= 0.005,
        "aspect_ratio_delta": round(aspect_delta, 6),
        "exact_pixel_match": same_size and html_rgba.tobytes() == pillow_rgba.tobytes(),
        "normalized_changed_percent": round(
            float(np.count_nonzero(changed_mask)) / pixel_count * 100,
            6,
        ),
        "normalized_significant_changed_percent": round(
            float(np.count_nonzero(significant_mask)) / pixel_count * 100,
            6,
        ),
        "mean_abs_rgba": [round(float(value), 6) for value in mean_abs_rgba],
        "rms_rgba": [round(float(value), 6) for value in rms_rgba],
        "max_abs_rgba": [int(value) for value in max_abs_rgba],
    }


def save_side_by_side(
    name: str,
    html_image: Image.Image,
    pillow_normalized: Image.Image,
    diff_visual: Image.Image,
    output_dir: Path,
) -> None:
    width, height = html_image.size
    canvas = Image.new("RGBA", (width * 3, height), (255, 255, 255, 255))
    canvas.alpha_composite(html_image, (0, 0))
    canvas.alpha_composite(pillow_normalized, (width, 0))
    canvas.alpha_composite(diff_visual, (width * 2, 0))
    save_image(canvas, output_dir / f"{name}-side-by-side.png")


async def screenshot_html(
    page: Page,
    html: str,
    selector: str,
    timeout: int,
) -> Image.Image:
    await page.set_content(html, wait_until="load", timeout=timeout)
    locator = page.locator(selector)
    if await locator.count() > 0:
        screenshot_bytes = await locator.screenshot(type="png", omit_background=True)
    else:
        screenshot_bytes = await page.screenshot(full_page=True, type="png")
    with Image.open(io.BytesIO(screenshot_bytes)) as image:
        image.load()
        return image.convert("RGBA")


async def render_html_images(
    executable_path: Path,
    timeout: int,
    block_external: bool,
    dataset: RenderDataset,
) -> dict[str, Image.Image]:
    subject_renderer = SubjectRenderer(render_mode="html")
    episode_renderer = EpisodeRenderer(render_mode="html")
    calendar_renderer = CalendarRenderer(render_mode="html")

    html_by_name = {
        "subject": subject_renderer._generate_html(
            "subject/subject.html",
            preprocess_data(dataset.subject_data),
            "subject",
        ),
        "episode": episode_renderer._generate_html(
            "update/episode.html",
            dataset.episode_data.model_dump(),
        ),
        "calendar": calendar_renderer._generate_html(
            "calendar/calendar.html",
            {"days": reorder_days(cast(list[Any], dataset.calendar_data))},
            "calendar",
        ),
    }

    async def abort_external_request(route: Any) -> None:
        await route.abort()

    launch_args = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--no-first-run",
        "--disable-extensions",
        "--disable-default-apps",
    ]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            executable_path=str(executable_path),
            args=launch_args,
        )
        try:
            context = await browser.new_context(
                viewport={"width": 1024, "height": 768},
                device_scale_factor=3,
                is_mobile=False,
                has_touch=False,
            )
            try:
                page = await context.new_page()
                if block_external:
                    await page.route("http://*/*", abort_external_request)
                    await page.route("https://*/*", abort_external_request)
                result = {}
                for name, html in html_by_name.items():
                    result[name] = await screenshot_html(
                        page,
                        html,
                        SELECTORS[name],
                        timeout,
                    )
                return result
            finally:
                await context.close()
        finally:
            await browser.close()


async def render_pillow_images(dataset: RenderDataset) -> dict[str, Image.Image]:
    subject_renderer = SubjectRenderer(render_mode="pillow")
    episode_renderer = EpisodeRenderer(render_mode="pillow")
    calendar_renderer = CalendarRenderer(render_mode="pillow")

    subject_payload = await subject_renderer.render_subject_card(dataset.subject_data)
    episode_payload = await episode_renderer.render_episode(dataset.episode_data)
    calendar_payload = await calendar_renderer.render_calendar(
        cast(list[Any], dataset.calendar_data)
    )
    payloads = {
        "subject": subject_payload,
        "episode": episode_payload,
        "calendar": calendar_payload,
    }
    missing = [name for name, payload in payloads.items() if not payload]
    if missing:
        raise RuntimeError(
            f"Pillow render returned empty payloads: {', '.join(missing)}"
        )
    return {
        name: decode_base64_png(payload)
        for name, payload in payloads.items()
        if payload
    }


def verdicts(result: dict[str, Any]) -> dict[str, str]:
    html = result["html"]
    pillow = result["pillow"]
    diff = result["diff"]
    alpha_match = (
        html["alpha_extrema"] == pillow["alpha_extrema"]
        and abs(html["translucent_percent"] - pillow["translucent_percent"]) <= 0.01
        and abs(html["transparent_percent"] - pillow["transparent_percent"]) <= 0.01
    )
    return {
        "dimensions": "PASS" if diff["same_dimensions"] else "FAIL",
        "aspect_ratio": "PASS" if diff["same_aspect_ratio"] else "FAIL",
        "alpha": "PASS" if alpha_match else "FAIL",
        "pixel_exact": "PASS" if diff["exact_pixel_match"] else "FAIL",
        "pixel_close": (
            "PASS"
            if diff["normalized_significant_changed_percent"] <= 0.1
            and max(diff["mean_abs_rgba"][:3]) <= 1.0
            else "FAIL"
        ),
    }


def build_report(
    results: dict[str, Any],
    output_dir: Path,
    block_external: bool,
    dataset: RenderDataset,
) -> str:
    lines = [
        "# Pillow vs Playwright render comparison",
        "",
        f"- Output directory: `{output_dir}`",
        f"- Data source: `{dataset.source}`",
        f"- Browser external network blocked: `{block_external}`",
        "- Pixel diff compares Playwright output against Pillow resized to Playwright dimensions when dimensions differ.",
    ]
    if dataset.notes:
        lines.append("- Data notes:")
        lines.extend(f"  - {note}" for note in dataset.notes)
    lines.extend(
        [
            "",
            "## Summary",
            "",
            "| renderer | html size | pillow size | html ratio | pillow ratio | dimensions | ratio | alpha | pixel exact | normalized changed | significant changed |",
            "| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | ---: | ---: |",
        ]
    )
    for name, result in results.items():
        verdict = verdicts(result)
        html = result["html"]
        pillow = result["pillow"]
        diff = result["diff"]
        lines.append(
            "| {name} | {html_size} | {pillow_size} | {html_ratio:.6f} | "
            "{pillow_ratio:.6f} | {dimensions} | {ratio} | {alpha} | "
            "{pixel_exact} | {changed:.3f}% | {significant:.3f}% |".format(
                name=name,
                html_size="x".join(str(value) for value in html["size"]),
                pillow_size="x".join(str(value) for value in pillow["size"]),
                html_ratio=html["aspect_ratio"],
                pillow_ratio=pillow["aspect_ratio"],
                dimensions=verdict["dimensions"],
                ratio=verdict["aspect_ratio"],
                alpha=verdict["alpha"],
                pixel_exact=verdict["pixel_exact"],
                changed=diff["normalized_changed_percent"],
                significant=diff["normalized_significant_changed_percent"],
            )
        )

    lines.extend(["", "## Alpha", ""])
    lines.append(
        "| renderer | html alpha | pillow alpha | html translucent | pillow translucent | html transparent | pillow transparent |"
    )
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: |")
    for name, result in results.items():
        html = result["html"]
        pillow = result["pillow"]
        lines.append(
            "| {name} | {html_alpha} | {pillow_alpha} | {html_trans:.3f}% | "
            "{pillow_trans:.3f}% | {html_clear:.3f}% | {pillow_clear:.3f}% |".format(
                name=name,
                html_alpha=html["alpha_extrema"],
                pillow_alpha=pillow["alpha_extrema"],
                html_trans=html["translucent_percent"],
                pillow_trans=pillow["translucent_percent"],
                html_clear=html["transparent_percent"],
                pillow_clear=pillow["transparent_percent"],
            )
        )

    lines.extend(["", "## Qualitative UI/Layout Notes", ""])
    for name, notes in QUALITATIVE_NOTES.items():
        lines.append(f"### {name}")
        lines.extend(f"- {note}" for note in notes)
        lines.append(
            f"- Artifacts: `{name}-html.png`, `{name}-pillow.png`, "
            f"`{name}-normalized-diff.png`, `{name}-side-by-side.png`."
        )
        lines.append("")

    lines.extend(
        [
            "## Thresholds",
            "",
            "- Aspect ratio PASS: absolute ratio delta <= 0.005.",
            "- Practical visual target: normalized significant changed pixels <= 35%; exact/glyph-level browser parity is diagnostic only.",
            "- Alpha PASS: alpha extrema match and transparent/translucent percentages differ by <= 0.01%.",
        ]
    )
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> int:
    if not args.executable_path.exists():
        raise FileNotFoundError(f"Chrome executable not found: {args.executable_path}")

    timestamp = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    output_dir = (
        args.output_dir
        or Path("rendered_images") / f"render-mode-comparison-{timestamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset = await load_dataset(args)

    html_images, pillow_images = await asyncio.gather(
        render_html_images(
            args.executable_path,
            args.timeout,
            args.block_external,
            dataset,
        ),
        render_pillow_images(dataset),
    )

    results: dict[str, Any] = {}
    for name in ("subject", "episode", "calendar"):
        html_image = html_images[name]
        pillow_image = pillow_images[name]
        save_image(html_image, output_dir / f"{name}-html.png")
        save_image(pillow_image, output_dir / f"{name}-pillow.png")
        results[name] = {
            "html": image_metrics(html_image),
            "pillow": image_metrics(pillow_image),
            "diff": compare_images(name, html_image, pillow_image, output_dir),
            "qualitative_notes": QUALITATIVE_NOTES[name],
        }

    report = build_report(results, output_dir, args.block_external, dataset)
    metrics_path = output_dir / "metrics.json"
    report_path = output_dir / "report.md"
    metrics_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(report, encoding="utf-8")

    print(report)
    print(f"metrics: {metrics_path}")
    print(f"report: {report_path}")

    if args.strict:
        failures = [
            name
            for name, result in results.items()
            if "FAIL" in verdicts(result).values()
        ]
        if failures:
            print(f"strict parity failed: {', '.join(failures)}", file=sys.stderr)
            return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare HTML/Playwright and Pillow card rendering outputs."
    )
    parser.add_argument(
        "--data-source",
        choices=("fixture", "bangumi"),
        default="fixture",
        help="Use deterministic local fixtures or live Bangumi API data.",
    )
    parser.add_argument(
        "--subject-id",
        default=None,
        help="Bangumi subject id for --data-source bangumi. Defaults to the first live calendar item.",
    )
    parser.add_argument(
        "--subject-query",
        default=None,
        help="Bangumi subject search query for --data-source bangumi when --subject-id is not set.",
    )
    parser.add_argument(
        "--calendar-item-limit",
        type=int,
        default=None,
        help="Optional per-day item cap for live Bangumi calendar comparison output.",
    )
    parser.add_argument(
        "--access-token",
        default=None,
        help="Bangumi access token for --data-source bangumi. Defaults to BANGUMI_ACCESS_TOKEN.",
    )
    parser.add_argument(
        "--user-agent",
        default=None,
        help="User-Agent for Bangumi API requests. Defaults to BANGUMI_USER_AGENT or the plugin default.",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="Optional aiohttp proxy URL for Bangumi API requests. Defaults to BANGUMI_PROXY.",
    )
    parser.add_argument(
        "--api-max-retries",
        type=int,
        default=3,
        help="Maximum Bangumi API retry attempts for live data mode.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for PNGs, diff images, metrics.json, and report.md.",
    )
    parser.add_argument(
        "--executable-path",
        type=Path,
        default=DEFAULT_CHROME,
        help="Chromium/Chrome executable used by Playwright.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30000,
        help="Playwright set_content timeout in milliseconds.",
    )
    parser.add_argument(
        "--allow-external",
        action="store_true",
        help="Allow browser network requests such as remote web fonts and live Bangumi cover images.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when any renderer misses parity thresholds.",
    )
    args = parser.parse_args()
    if args.calendar_item_limit is not None and args.calendar_item_limit < 0:
        parser.error("--calendar-item-limit must be >= 0")
    args.block_external = not args.allow_external
    return args


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
