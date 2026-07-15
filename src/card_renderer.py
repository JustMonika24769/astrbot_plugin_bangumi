from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .entities import CalendarDay, Episode, Subject, SubscriptionView, UpdateReport

HtmlRender = Callable[..., Awaitable[str]]


class CardRenderError(RuntimeError):
    pass


class T2ICardRenderer:
    def __init__(self, html_render: HtmlRender, *, quality: int = 88) -> None:
        self._html_render = html_render
        self._quality = quality
        self._template_dir = Path(__file__).resolve().parent / "templates" / "cards"
        self._css = (self._template_dir / "card.css").read_text(encoding="utf-8")
        self._templates: dict[str, str] = {}

    def _template(self, name: str) -> str:
        if name not in self._templates:
            content = (self._template_dir / f"{name}.html").read_text(encoding="utf-8")
            self._templates[name] = content.replace("/*__CARD_CSS__*/", self._css)
        return self._templates[name]

    async def render(self, template: str, data: dict[str, Any]) -> str:
        try:
            path = await self._html_render(
                self._template(template),
                data,
                return_url=False,
                options={
                    "full_page": True,
                    "type": "jpeg",
                    "quality": self._quality,
                },
            )
        except Exception as exc:
            raise CardRenderError(f"AstrBot T2I 渲染失败: {exc}") from exc
        if not path:
            raise CardRenderError("AstrBot T2I 未返回图片路径")
        return str(path)

    async def subject_card(
        self,
        subject: Subject,
        *,
        latest: Episode | None = None,
        subscribed: bool = False,
    ) -> str:
        return await self.render(
            "subject",
            {
                "subject": self._subject_data(subject),
                "latest": self._episode_data(latest) if latest else None,
                "subscribed": subscribed,
            },
        )

    async def search_card(
        self, query: str, subjects: list[Subject], *, heading: str = "搜索结果"
    ) -> str:
        return await self.render(
            "search",
            {
                "query": query,
                "heading": heading,
                "subjects": [self._subject_data(subject) for subject in subjects],
            },
        )

    async def calendar_card(
        self, days: list[CalendarDay], *, heading: str, subheading: str
    ) -> str:
        return await self.render(
            "calendar",
            {
                "heading": heading,
                "subheading": subheading,
                "days": [
                    {
                        "name": day.weekday_name,
                        "is_today": day.is_today,
                        "count": len(day.items),
                        "items": [self._subject_data(item) for item in day.items],
                    }
                    for day in days
                ],
            },
        )

    async def subscriptions_card(self, subscriptions: list[SubscriptionView]) -> str:
        return await self.render(
            "subscriptions",
            {
                "subscriptions": [
                    {
                        "subject_id": item.subject_id,
                        "title": item.title,
                        "cover_url": item.cover_url,
                        "progress": self._progress(
                            item.current_episode, item.total_episodes
                        ),
                        "current_episode": item.current_episode,
                        "last_notified_episode": item.last_notified_episode,
                        "total_episodes": item.total_episodes,
                        "broadcast_time": item.broadcast_time or "未设置",
                        "last_checked_at": self._display_datetime(item.last_checked_at),
                        "pending": item.is_pending,
                        "error": item.delivery_error or item.subject_error or "",
                    }
                    for item in subscriptions
                ]
            },
        )

    async def update_card(
        self,
        subject: Subject,
        episode: Episode,
        *,
        previous_episode: int,
    ) -> str:
        return await self.render(
            "update",
            {
                "subject": self._subject_data(subject),
                "episode": self._episode_data(episode),
                "previous_episode": previous_episode,
                "missed_count": max(0, episode.number - previous_episode - 1),
            },
        )

    async def report_card(self, report: UpdateReport) -> str:
        return await self.render(
            "report",
            {
                "summary": report.summary,
                "subjects_total": report.subjects_total,
                "subjects_checked": report.subjects_checked,
                "pending": report.pending_deliveries,
                "delivered": report.delivered,
                "failed": report.failed,
                "details": report.details[-12:],
            },
        )

    async def help_card(self, commands: list[dict[str, str]]) -> str:
        return await self.render("help", {"commands": commands})

    @classmethod
    def _subject_data(cls, subject: Subject) -> dict[str, Any]:
        return {
            "id": subject.id,
            "title": subject.title,
            "original_title": subject.original_title,
            "summary": cls._clean_text(subject.summary, 420),
            "air_date": subject.air_date or "待定",
            "platform": subject.platform or cls._type_label(subject.type),
            "total_episodes": subject.total_episodes,
            "score": f"{subject.score:.1f}" if subject.score > 0 else "--",
            "score_count": subject.score_count,
            "rank": subject.rank,
            "cover_url": subject.cover_url,
            "tags": list(subject.tags[:6]),
            "url": subject.url,
        }

    @classmethod
    def _episode_data(cls, episode: Episode) -> dict[str, Any]:
        return {
            "id": episode.id,
            "number": episode.number,
            "title": episode.title,
            "original_title": (
                episode.name
                if episode.name_cn and episode.name != episode.name_cn
                else ""
            ),
            "air_date": episode.air_date or "日期待定",
            "summary": cls._clean_text(episode.summary, 360),
            "duration": episode.duration,
            "comments": episode.comments,
            "url": episode.url,
        }

    @staticmethod
    def _clean_text(text: str, limit: int) -> str:
        normalized = re.sub(r"\s+", " ", text or "").strip()
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[: limit - 1].rstrip()}…"

    @staticmethod
    def _progress(current: int, total: int) -> int:
        if total <= 0:
            return 0
        return max(0, min(100, round(current / total * 100)))

    @staticmethod
    def _type_label(subject_type: int) -> str:
        return {
            1: "书籍",
            2: "动画",
            3: "音乐",
            4: "游戏",
            6: "三次元",
        }.get(subject_type, "条目")

    @staticmethod
    def _display_datetime(value: str | None) -> str:
        if not value:
            return "尚未检查"
        return value.replace("T", " ")[:16]
