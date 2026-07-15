from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class Subject:
    id: int
    type: int
    name: str
    name_cn: str = ""
    summary: str = ""
    air_date: str = ""
    platform: str = ""
    total_episodes: int = 0
    score: float = 0.0
    score_count: int = 0
    rank: int = 0
    cover_url: str = ""
    tags: tuple[str, ...] = ()

    @property
    def title(self) -> str:
        return self.name_cn.strip() or self.name.strip() or f"条目 {self.id}"

    @property
    def original_title(self) -> str:
        if self.name_cn.strip() and self.name.strip() != self.name_cn.strip():
            return self.name.strip()
        return ""

    @property
    def url(self) -> str:
        return f"https://bgm.tv/subject/{self.id}"


@dataclass(frozen=True, slots=True)
class Episode:
    id: int
    subject_id: int
    type: int
    number: int
    sort: int
    name: str = ""
    name_cn: str = ""
    air_date: str = ""
    summary: str = ""
    duration: str = ""
    comments: int = 0

    @property
    def title(self) -> str:
        return self.name_cn.strip() or self.name.strip() or f"第 {self.number} 集"

    @property
    def url(self) -> str:
        return f"https://bgm.tv/ep/{self.id}"


@dataclass(frozen=True, slots=True)
class CalendarDay:
    weekday_id: int
    weekday_name: str
    items: tuple[Subject, ...]
    is_today: bool = False


@dataclass(frozen=True, slots=True)
class TrackedSubject:
    subject_id: str
    title: str
    name: str
    cover_url: str
    air_date: str
    total_episodes: int
    current_episode: int
    broadcast_time: str | None
    last_checked_at: str | None
    last_error: str | None


@dataclass(frozen=True, slots=True)
class SubscriptionView:
    session_id: str
    subject_id: str
    title: str
    cover_url: str
    total_episodes: int
    current_episode: int
    last_notified_episode: int
    broadcast_time: str | None
    last_checked_at: str | None
    subject_error: str | None
    delivery_error: str | None

    @property
    def is_pending(self) -> bool:
        return self.current_episode > self.last_notified_episode


@dataclass(frozen=True, slots=True)
class SubscribeResult:
    subject: Subject
    latest_episode: Episode | None
    created: bool


@dataclass(slots=True)
class UpdateReport:
    subjects_total: int = 0
    subjects_checked: int = 0
    no_episode: int = 0
    pending_deliveries: int = 0
    delivered: int = 0
    failed: int = 0
    skipped: bool = False
    details: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.skipped:
            return "上一轮检查仍在执行，本轮已跳过"
        return (
            f"检查 {self.subjects_checked}/{self.subjects_total} 部，"
            f"待通知 {self.pending_deliveries}，"
            f"成功 {self.delivered}，失败 {self.failed}"
        )


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
