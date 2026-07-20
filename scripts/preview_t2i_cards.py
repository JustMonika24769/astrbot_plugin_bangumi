from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = PROJECT_ROOT.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from astrbot.core import html_renderer  # noqa: E402
from astrbot_plugin_bangumi.src.bangumi_client import BangumiClient  # noqa: E402
from astrbot_plugin_bangumi.src.card_renderer import T2ICardRenderer  # noqa: E402
from astrbot_plugin_bangumi.src.entities import (  # noqa: E402
    CalendarDay,
    Episode,
    Subject,
    SubscriptionView,
    UpdateReport,
)


def subject_fixture() -> Subject:
    return Subject(
        id=454083,
        type=2,
        name="Girls Band Cry",
        name_cn="少女乐队的呐喊",
        summary=(
            "高中二年级退学，独自来到东京准备升学的主人公，"
            "在陌生城市里遇见了同样带着伤痕生活的伙伴。"
            "她们通过音乐确认自己的声音，也重新理解失败与选择。"
        ),
        air_date="2024-04-05",
        platform="TV",
        total_episodes=13,
        score=8.5,
        score_count=18234,
        rank=108,
        cover_url="https://lain.bgm.tv/pic/cover/l/63/13/454083_Z0pF4.jpg",
        tags=("原创", "音乐", "青春", "乐队", "成长", "东映动画"),
    )


def episode_fixture() -> Episode:
    return Episode(
        id=1364357,
        subject_id=454083,
        type=0,
        number=11,
        sort=11,
        name="The Center of the World",
        name_cn="世界的中心",
        air_date="2024-06-14",
        summary="面对重要演出与彼此不同的选择，成员们必须决定乐队真正想要表达的东西。",
        duration="00:23:40",
        comments=456,
    )


async def render_previews(
    output_dir: Path,
    only: set[str] | None = None,
) -> list[Path]:
    await html_renderer.initialize()
    renderer = T2ICardRenderer(html_renderer.render_custom_template, quality=90)
    subject = subject_fixture()
    async with aiohttp.ClientSession(trust_env=True) as session:
        client = BangumiClient(
            session,
            access_token="",
            user_agent="AstrBot-Bangumi-Preview/2.0",
            proxy_url=None,
            timeout_seconds=25,
            max_retries=2,
        )
        subject = await client.with_embedded_cover(subject)
    episode = episode_fixture()
    subjects = [
        subject,
        Subject(
            id=525565,
            type=2,
            name="Sousou no Frieren 2nd Season",
            name_cn="葬送的芙莉莲 第二季",
            air_date="2026-01-16",
            platform="TV",
            total_episodes=0,
            score=8.8,
            score_count=9210,
            rank=34,
            tags=("奇幻", "旅行", "漫画改"),
        ),
        Subject(
            id=569116,
            type=2,
            name="Sample Series",
            name_cn="示例新番",
            air_date="2026-07-03",
            platform="TV",
            total_episodes=12,
            score=7.4,
            score_count=782,
            rank=1850,
            tags=("日常", "校园"),
        ),
    ]
    subscriptions = [
        SubscriptionView(
            session_id="aiocqhttp:group:10000",
            subject_id=str(subject.id),
            title=subject.title,
            cover_url=subject.cover_url,
            total_episodes=13,
            current_episode=11,
            last_notified_episode=10,
            broadcast_date="2024-04-05",
            broadcast_time="23:30",
            last_checked_at="2026-07-14T19:30:00",
            subject_error=None,
            delivery_error="上次发送失败，等待下一轮重试",
        )
    ]
    report = UpdateReport(
        subjects_total=4,
        subjects_checked=4,
        pending_deliveries=1,
        delivered=0,
        failed=1,
        details=[
            "《少女乐队的呐喊》API EP11，待通知 1 个会话",
            "《示例新番》API EP2，待通知 0 个会话",
        ],
    )

    renders = {
        "subject": lambda: renderer.subject_card(
            subject, latest=episode, subscribed=True
        ),
        "search": lambda: renderer.search_card("乐队", subjects),
        "calendar": lambda: renderer.calendar_card(
            [
                CalendarDay(1, "星期一", tuple(subjects[:2]), False),
                CalendarDay(2, "星期二", tuple(subjects[1:]), True),
            ],
            heading="每周放送表",
            subheading="T2I 视觉预览",
        ),
        "subscriptions": lambda: renderer.subscriptions_card(subscriptions),
        "update": lambda: renderer.update_card(subject, episode, previous_episode=8),
        "report": lambda: renderer.report_card(report),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for name, render in renders.items():
        if only and name not in only:
            continue
        source = Path(await render())
        target = output_dir / f"{name}.jpg"
        shutil.copy2(source, target)
        outputs.append(target)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="使用 AstrBot T2I 渲染 2.0 卡片预览")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "rendered_images" / "t2i-v2",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=(
            "subject",
            "search",
            "calendar",
            "subscriptions",
            "update",
            "report",
        ),
        help="只渲染指定卡片，可同时指定多个名称",
    )
    args = parser.parse_args()
    outputs = asyncio.run(
        render_previews(args.output_dir, set(args.only) if args.only else None)
    )
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
