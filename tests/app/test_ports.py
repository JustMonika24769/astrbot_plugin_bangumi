from __future__ import annotations

from typing import assert_type

from astrbot_plugin_bangumi.src.app import (
    AppRenderMode,
    BangumiApiPort,
    CalendarRendererPort,
    EpisodeRendererPort,
    GroupNotifierPort,
    LocalSubscriptionCandidateRecord,
    MonitoredSubjectRecord,
    RenderConfigPort,
    SubjectRendererPort,
    SubscriptionStorePort,
)
from astrbot_plugin_bangumi.src.domain.contracts import (
    CalendarDay,
    EpisodeCardVariant,
    EpisodeListResponse,
    RenderData,
    SearchSubjectsResponse,
    SubjectDetailsResponse,
)
from astrbot_plugin_bangumi.src.domain.schemas import Episode
from astrbot_plugin_bangumi.src.domain.types import ImageSize


class FakeBangumiApi:
    async def search_subjects(
        self,
        keyword: str,
        limit: int = 5,
        offset: int = 0,
        subject_type: list[int] | None = None,
        subject_tags: list[str] | None = None,
    ) -> SearchSubjectsResponse:
        return {"data": [{"id": 1, "name": keyword}]}

    async def get_subject_details(self, subject_id: str) -> SubjectDetailsResponse:
        return {"id": subject_id, "name": "subject"}

    async def get_subject_episodes(self, subject_id: int) -> EpisodeListResponse:
        return {"data": []}

    async def get_calendar(self) -> list[CalendarDay]:
        return []

    async def get_latest_episode(self, subject_id: int) -> Episode | None:
        return None

    async def get_subject_base64image(
        self, subject_id: str, size: ImageSize
    ) -> str | None:
        return None


class FakeStore:
    def subscribe_subject(
        self,
        group_id: str,
        subject_id: str,
        name: str,
        air_date: str = "",
        total_episodes: int = 0,
    ) -> bool:
        return True

    def remove_subscription(self, group_id: str, subject_id: str) -> bool:
        return True

    def find_group_subscription_candidates(
        self, group_id: str, keyword: str, limit: int = 5
    ) -> list[LocalSubscriptionCandidateRecord]:
        return [LocalSubscriptionCandidateRecord(subject_id="1", name="subject")]

    def get_monitored_subjects(self) -> list[MonitoredSubjectRecord]:
        return [
            MonitoredSubjectRecord(subject_id="1", name="subject", current_episode=1)
        ]

    def update_subject_episode(self, subject_id: str, new_episode: int) -> bool:
        return True

    def get_subject_subscribers(self, subject_id: str) -> list[str]:
        return ["group"]


class FakeConfig:
    def get_render_server_url(self) -> str:
        return "rpc"

    def get_render_mode(self) -> AppRenderMode:
        return "html"

    def get_max_retries(self) -> int:
        return 1

    def get_episode_card_template(self) -> EpisodeCardVariant:
        return "cinematic_poster"


class FakeSubjectRenderer:
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
        return ["b64"]


class FakeCalendarRenderer:
    async def render_calendar(
        self,
        calendar_data: list[CalendarDay],
        rpc_url: str | None = None,
        headless: bool = True,
        max_retries: int = 3,
    ) -> str | None:
        return "b64"


class FakeEpisodeRenderer:
    async def render_episode(
        self,
        episode_data: Episode,
        rpc_url: str | None = None,
        headless: bool = True,
        max_retries: int = 3,
        *,
        variant: EpisodeCardVariant | None = None,
    ) -> str | None:
        return "b64"


class FakeNotifier:
    async def send_episode_update(
        self, group_id: str, image_base64: str | None, fallback_text: str
    ) -> None:
        return None


def test_port_protocols_accept_structural_implementations() -> None:
    api: BangumiApiPort = FakeBangumiApi()
    store: SubscriptionStorePort = FakeStore()
    config: RenderConfigPort = FakeConfig()
    subject_renderer: SubjectRendererPort = FakeSubjectRenderer()
    calendar_renderer: CalendarRendererPort = FakeCalendarRenderer()
    episode_renderer: EpisodeRendererPort = FakeEpisodeRenderer()
    notifier: GroupNotifierPort = FakeNotifier()

    assert_type(api, BangumiApiPort)
    assert_type(store, SubscriptionStorePort)
    assert_type(config, RenderConfigPort)
    assert_type(subject_renderer, SubjectRendererPort)
    assert_type(calendar_renderer, CalendarRendererPort)
    assert_type(episode_renderer, EpisodeRendererPort)
    assert_type(notifier, GroupNotifierPort)
