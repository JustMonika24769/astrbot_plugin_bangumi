from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import datetime as dt
import io
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import aiohttp
import numpy as np
from PIL import Image, ImageChops, ImageDraw

if TYPE_CHECKING:
    from astrbot_plugin_bangumi.src.domain.schemas import Episode

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = PROJECT_ROOT.parent
RENDERED_PREVIEW_DIR = PROJECT_ROOT / "rendered_images/episode-card-variants"
PIPELINE_PREVIEW_DIR = (
    PROJECT_ROOT / ".pipeline-workspace/previews/episode-card-variants"
)
DEFAULT_SUBJECT_QUERY = "葬送的芙莉莲"
DEFAULT_USER_AGENT = (
    "AstrBot-Bangumi-Plugin/episode-variant-preview "
    "(https://github.com/united-pooh/astrbot_plugin_bangumi)"
)

if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))


@dataclass(frozen=True)
class PreviewRunResult:
    data_source: str
    data_notes: list[str]
    preview_paths: list[tuple[str, Path, Path]]
    alignment_metrics: list[dict[str, Any]] = field(default_factory=list)


def build_cover_data_uri() -> str:
    image = Image.new("RGB", (720, 960), (32, 42, 54))
    draw = ImageDraw.Draw(image)

    for y in range(image.height):
        ratio = y / max(image.height - 1, 1)
        red = int(30 + (198 - 30) * ratio)
        green = int(52 + (112 - 52) * ratio)
        blue = int(80 + (150 - 80) * ratio)
        draw.line((0, y, image.width, y), fill=(red, green, blue))

    draw.rectangle((54, 64, 666, 896), outline=(244, 230, 194), width=14)
    draw.rectangle((92, 110, 628, 498), fill=(38, 58, 84))
    draw.ellipse((182, 150, 538, 506), fill=(235, 132, 89))
    draw.polygon(
        [
            (94, 712),
            (272, 560),
            (396, 686),
            (514, 574),
            (628, 716),
            (628, 850),
            (94, 850),
        ],
        fill=(246, 239, 219),
    )
    draw.rectangle((132, 766, 588, 828), fill=(54, 67, 78))
    draw.line((132, 796, 588, 796), fill=(244, 230, 194), width=4)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def build_fixture_episode() -> Episode:
    from astrbot_plugin_bangumi.src.domain.schemas import Episode

    episode = Episode(
        id=20260517,
        subject_id=525565,
        type=0,
        ep=7,
        sort=7,
        name="第7話 星明かりのリハーサル",
        name_cn="第7话 星光下的彩排",
        airdate="2026-05-17",
        comment=42,
        disc=0,
        duration="00:24:10",
        duration_seconds=1450,
        desc=(
            "临近正式演出，社团成员在夜晚的礼堂完成最后一次彩排。"
            "旧舞台的灯光重新亮起，也让主角确认了想要传达给大家的心意。"
        ),
    )
    return episode.model_copy(update={"image_url": build_cover_data_uri()})


def image_url_from_subject(subject_data: dict[str, Any]) -> str:
    images = subject_data.get("images")
    if isinstance(images, dict):
        for key in ("large", "common", "medium", "small", "grid"):
            value = images.get(key)
            if isinstance(value, str) and value:
                return value
    image = subject_data.get("image")
    return image if isinstance(image, str) else ""


def episode_from_raw_list(raw_episodes: list[dict[str, Any]]) -> Episode | None:
    from astrbot_plugin_bangumi.src.domain.schemas import Episode

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

    aired_with_comments: list[Episode] = []
    aired: list[Episode] = []
    for episode in normal_episodes:
        is_aired = True
        if episode.airdate:
            try:
                is_aired = (
                    dt.datetime.strptime(
                        episode.airdate,
                        "%Y-%m-%d",
                    ).date()
                    <= today
                )
            except ValueError:
                is_aired = True
        if is_aired:
            aired.append(episode)
            if episode.comment > 0:
                aired_with_comments.append(episode)
    return (aired_with_comments or aired or normal_episodes)[-1]


async def load_bangumi_episode(args: argparse.Namespace) -> tuple[Episode, list[str]]:
    from astrbot_plugin_bangumi.src.api import BangumiService
    from astrbot_plugin_bangumi.src.domain.schemas import Episode

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
        subject_id = args.subject_id
        if subject_id is None:
            search_result = await service.search_subjects(
                args.subject_query,
                limit=1,
                subject_type=[2],
            )
            items = search_result.get("data", [])
            if not items or items[0].get("id") is None:
                raise RuntimeError(
                    f"No Bangumi subject found for {args.subject_query!r}"
                )
            subject_id = str(items[0]["id"])

        subject_data = dict(await service.get_subject_details(str(subject_id)))
        episode_response = await service.get_subject_episodes(int(subject_id))
        raw_episodes = [
            cast(dict[str, Any], item)
            for item in episode_response.get("data", [])
            if isinstance(item, dict)
        ]
        image_url = image_url_from_subject(subject_data)
        episode = episode_from_raw_list(raw_episodes)
        if episode is None:
            subject_name = str(
                subject_data.get("name_cn")
                or subject_data.get("name")
                or f"Bangumi subject {subject_id}"
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

    title = subject_data.get("name_cn") or subject_data.get("name") or "unknown"
    return episode, [
        f"Bangumi API subject_id: {subject_id}",
        f"Bangumi API subject title: {title}",
        f"Bangumi API episode id: {episode.id}",
        f"Bangumi API episode label: EP.{episode.sort:02d}",
    ]


async def load_episode(args: argparse.Namespace) -> tuple[Episode, list[str], str]:
    if args.data_source == "fixture":
        return (
            build_fixture_episode(),
            ["Using deterministic local fixture data."],
            "fixture",
        )
    episode, notes = await load_bangumi_episode(args)
    return episode, notes, "bangumi"


async def render_variants(
    episode: Episode | None = None,
) -> list[tuple[str, Path, Path]]:
    from astrbot_plugin_bangumi.src.domain import EPISODE_CARD_VARIANTS
    from astrbot_plugin_bangumi.src.render.episode_renderer import EpisodeRenderer

    RENDERED_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    PIPELINE_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    renderer = EpisodeRenderer(render_mode="pillow")
    selected_episode = episode or build_fixture_episode()
    preview_paths: list[tuple[str, Path, Path]] = []

    for variant in EPISODE_CARD_VARIANTS:
        encoded_png = await renderer.render_episode(selected_episode, variant=variant)
        if encoded_png is None:
            raise RuntimeError(f"Episode renderer returned no image for {variant}")

        png_bytes = base64.b64decode(encoded_png)
        rendered_path = RENDERED_PREVIEW_DIR / f"{variant}.png"
        pipeline_path = PIPELINE_PREVIEW_DIR / f"{variant}.png"
        rendered_path.write_bytes(png_bytes)
        pipeline_path.write_bytes(png_bytes)
        preview_paths.append((variant, rendered_path, pipeline_path))

    return preview_paths


def decode_png_bytes(png_bytes: bytes) -> Image.Image:
    with Image.open(io.BytesIO(png_bytes)) as image:
        image.load()
        return image.convert("RGBA")


def image_to_data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def pixel_metrics(left: Image.Image, right: Image.Image) -> dict[str, Any]:
    if left.size != right.size:
        right = right.resize(left.size, Image.Resampling.LANCZOS)
    left_array = np.asarray(left.convert("RGBA"), dtype=np.uint8).copy()
    right_array = np.asarray(right.convert("RGBA"), dtype=np.uint8).copy()
    left_array[left_array[:, :, 3] == 0, :3] = 0
    right_array[right_array[:, :, 3] == 0, :3] = 0
    diff_array = np.abs(
        left_array.astype(np.int16) - right_array.astype(np.int16)
    ).astype(np.float32)
    changed_mask = np.any(diff_array > 0, axis=2)
    significant_mask = np.any(diff_array[:, :, :3] > 8, axis=2) | (
        diff_array[:, :, 3] > 0
    )
    pixels = left.width * left.height
    exact_pixel_match = not bool(np.any(diff_array))
    significant_changed_percent = round(
        float(np.count_nonzero(significant_mask)) / pixels * 100,
        6,
    )
    return {
        "size": [left.width, left.height],
        "exact_pixel_match": exact_pixel_match,
        "pixel_aligned": significant_changed_percent == 0.0,
        "changed_percent": round(
            float(np.count_nonzero(changed_mask)) / pixels * 100,
            6,
        ),
        "significant_changed_percent": significant_changed_percent,
        "max_abs_rgba": [int(value) for value in diff_array.max(axis=(0, 1))],
        "mean_abs_rgba": [
            round(float(value), 6) for value in diff_array.mean(axis=(0, 1))
        ],
    }


async def verify_pixel_alignment(
    episode: Episode,
    preview_paths: list[tuple[str, Path, Path]],
    *,
    headless: bool = True,
    timeout: int = 30000,
) -> list[dict[str, Any]]:
    from astrbot_plugin_bangumi.src.render.episode_renderer import EpisodeRenderer

    renderer = EpisodeRenderer(render_mode="html")
    metrics: list[dict[str, Any]] = []

    for variant, rendered_path, _pipeline_path in preview_paths:
        render_data = episode.model_dump()
        render_data["episode_variant"] = variant
        render_data["pillow_card_data_uri"] = image_to_data_uri(rendered_path)
        html = renderer._generate_html("update/episode.html", render_data)
        html_payload = await renderer._capture_screenshot(
            html,
            "#card-container",
            headless=headless,
            timeout=timeout,
        )
        if html_payload is None:
            raise RuntimeError(f"HTML screenshot returned no image for {variant}")

        html_image = decode_png_bytes(base64.b64decode(html_payload))
        pillow_image = decode_png_bytes(rendered_path.read_bytes())
        html_path = RENDERED_PREVIEW_DIR / f"{variant}-html.png"
        diff_path = RENDERED_PREVIEW_DIR / f"{variant}-pixel-diff.png"
        html_image.save(html_path)
        diff = ImageChops.difference(pillow_image, html_image)
        diff.save(diff_path)

        variant_metrics = {
            "variant": variant,
            "pillow_path": str(rendered_path),
            "html_path": str(html_path),
            "diff_path": str(diff_path),
            **pixel_metrics(pillow_image, html_image),
        }
        metrics.append(variant_metrics)

    metrics_path = RENDERED_PREVIEW_DIR / "pixel_alignment.json"
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metrics


async def run(args: argparse.Namespace) -> PreviewRunResult:
    episode, data_notes, data_source = await load_episode(args)
    preview_paths = await render_variants(episode)
    alignment_metrics: list[dict[str, Any]] = []
    if args.verify_pixel_alignment:
        alignment_metrics = await verify_pixel_alignment(
            episode,
            preview_paths,
            headless=not args.headed,
            timeout=args.timeout,
        )
    return PreviewRunResult(
        data_source=data_source,
        data_notes=data_notes,
        preview_paths=preview_paths,
        alignment_metrics=alignment_metrics,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render the episode card variants with real Bangumi data."
    )
    parser.add_argument(
        "--data-source",
        choices=("bangumi", "fixture"),
        default="bangumi",
        help="Use live Bangumi API data by default; fixture is for deterministic tests.",
    )
    parser.add_argument(
        "--subject-id",
        default=None,
        help="Bangumi subject id. Defaults to searching the configured subject query.",
    )
    parser.add_argument(
        "--subject-query",
        default=DEFAULT_SUBJECT_QUERY,
        help="Bangumi subject query used when --subject-id is omitted.",
    )
    parser.add_argument(
        "--access-token",
        default=None,
        help="Bangumi access token. Defaults to BANGUMI_ACCESS_TOKEN.",
    )
    parser.add_argument(
        "--user-agent",
        default=None,
        help="Bangumi User-Agent. Defaults to BANGUMI_USER_AGENT or a script default.",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="Optional aiohttp proxy URL. Defaults to BANGUMI_PROXY.",
    )
    parser.add_argument(
        "--api-max-retries",
        type=int,
        default=3,
        help="Maximum Bangumi API retry attempts.",
    )
    parser.add_argument(
        "--verify-pixel-alignment",
        action="store_true",
        help="Render the HTML path and write per-variant Pillow-vs-HTML pixel metrics.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser pixel-alignment verification in headed mode.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30000,
        help="Browser screenshot timeout in milliseconds for pixel alignment.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        result = asyncio.run(run(args))

    print(f"data source: {result.data_source}")
    for note in result.data_notes:
        print(f"data note: {note}")
    for variant, rendered_path, pipeline_path in result.preview_paths:
        print(f"generated {variant}: {rendered_path} and {pipeline_path}")
    for metric in result.alignment_metrics:
        print(
            "pixel alignment {variant}: aligned={aligned} bit_exact={exact} "
            "changed={changed}% significant={significant}%".format(
                variant=metric["variant"],
                aligned=metric["pixel_aligned"],
                exact=metric["exact_pixel_match"],
                changed=metric["changed_percent"],
                significant=metric["significant_changed_percent"],
            )
        )


if __name__ == "__main__":
    main()
