from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from ..domain.contracts import (
    CalendarDay,
    EpisodeCardVariant,
    EpisodeListResponse,
    RenderData,
    SearchSubjectsResponse,
    SubjectDetailsResponse,
)
from ..domain.schemas import Episode
from ..domain.types import ImageSize

AppRenderMode = Literal["html", "pillow"]


@dataclass(frozen=True, slots=True)
class LocalSubscriptionCandidateRecord:
    subject_id: str
    name: str


@dataclass(frozen=True, slots=True)
class MonitoredSubjectRecord:
    subject_id: str
    name: str
    current_episode: int
    air_date: str = ""
    total_episodes: int = 0


class BangumiApiPort(Protocol):
    async def search_subjects(
        self,
        keyword: str,
        limit: int = 5,
        offset: int = 0,
        subject_type: list[int] | None = None,
        subject_tags: list[str] | None = None,
    ) -> SearchSubjectsResponse: ...

    async def get_subject_details(self, subject_id: str) -> SubjectDetailsResponse: ...

    async def get_subject_episodes(self, subject_id: int) -> EpisodeListResponse: ...

    async def get_calendar(self) -> list[CalendarDay]: ...

    async def get_latest_episode(self, subject_id: int) -> Episode | None: ...

    async def get_subject_base64image(
        self, subject_id: str, size: ImageSize
    ) -> str | None: ...


class SubscriptionStorePort(Protocol):
    def subscribe_subject(
        self,
        group_id: str,
        subject_id: str,
        name: str,
        air_date: str = "",
        total_episodes: int = 0,
    ) -> bool: ...

    def remove_subscription(self, group_id: str, subject_id: str) -> bool: ...

    def find_group_subscription_candidates(
        self, group_id: str, keyword: str, limit: int = 5
    ) -> list[LocalSubscriptionCandidateRecord]: ...

    def get_monitored_subjects(self) -> list[MonitoredSubjectRecord]: ...

    def update_subject_episode(self, subject_id: str, new_episode: int) -> bool: ...

    def get_subject_subscribers(self, subject_id: str) -> list[str]: ...


class RenderConfigPort(Protocol):
    def get_render_server_url(self) -> str: ...

    def get_render_mode(self) -> AppRenderMode: ...

    def get_max_retries(self) -> int: ...

    def get_episode_card_template(self) -> EpisodeCardVariant: ...


class SubjectRendererPort(Protocol):
    async def render_batch_subject_cards_to_base64(
        self,
        data_list: list[RenderData],
        rpc_url: str | None = None,
        headless: bool = True,
        wait_time: int = 0,
        max_retries: int = 3,
        timeout: int = 30000,
        max_concurrency: int = 3,
    ) -> list[str]: ...


class CalendarRendererPort(Protocol):
    async def render_calendar(
        self,
        calendar_data: list[CalendarDay],
        rpc_url: str | None = None,
        headless: bool = True,
        max_retries: int = 3,
    ) -> str | None: ...


class EpisodeRendererPort(Protocol):
    async def render_episode(
        self,
        episode_data: Episode,
        rpc_url: str | None = None,
        headless: bool = True,
        max_retries: int = 3,
        *,
        variant: EpisodeCardVariant | None = None,
    ) -> str | None: ...


class GroupNotifierPort(Protocol):
    async def send_episode_update(
        self, group_id: str, image_base64: str | None, fallback_text: str
    ) -> None: ...


__all__ = [
    "AppRenderMode",
    "BangumiApiPort",
    "CalendarRendererPort",
    "EpisodeRendererPort",
    "GroupNotifierPort",
    "LocalSubscriptionCandidateRecord",
    "MonitoredSubjectRecord",
    "RenderConfigPort",
    "SubjectRendererPort",
    "SubscriptionStorePort",
]
