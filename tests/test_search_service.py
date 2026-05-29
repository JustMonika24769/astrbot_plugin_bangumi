from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from astrbot_plugin_bangumi.src.app.responses import AppImages, AppText
from astrbot_plugin_bangumi.src.domain.contracts import (
    CalendarDay,
    EpisodeListResponse,
    RenderData,
    SearchSubjectsResponse,
    SubjectDetailsResponse,
)
from astrbot_plugin_bangumi.src.services import SearchService


@pytest.mark.asyncio
async def test_handle_calendar_success() -> None:
    api = FakeBangumiApi(calendar_result=[{"weekday": {"id": 1}, "items": []}])
    calendar_renderer = FakeCalendarRenderer(base64_result="fake_base64")
    search_service = _service(api=api, calendar_renderer=calendar_renderer)

    result = await search_service.handle_calendar()

    assert result == AppImages(("fake_base64",))
    assert api.calendar_calls == 1
    assert calendar_renderer.calls == [
        CalendarRenderCall(
            calendar_data=[{"weekday": {"id": 1}, "items": []}],
            rpc_url="https://api.unitedpooh.top/rpc",
            max_retries=1,
        )
    ]


@pytest.mark.asyncio
async def test_handle_subject_search_no_query() -> None:
    search_service = _service()

    result = await search_service.handle_subject_search(query="")

    assert result == AppText("❌ 请提供搜索关键词")


def test_search_service_keeps_injected_ports() -> None:
    api = FakeBangumiApi()
    render_config = FakeRenderConfig()
    subject_renderer = FakeSubjectRenderer()
    calendar_renderer = FakeCalendarRenderer()

    search_service = SearchService(
        bangumi_api=api,
        render_config=render_config,
        subject_renderer=subject_renderer,
        calendar_renderer=calendar_renderer,
    )

    assert search_service.bangumi_api is api
    assert search_service.render_config is render_config
    assert search_service.subject_renderer is subject_renderer
    assert search_service.calendar_renderer is calendar_renderer


@dataclass
class FakeBangumiApi:
    search_result: SearchSubjectsResponse = field(default_factory=lambda: {"data": []})
    subject_details: dict[str, SubjectDetailsResponse] = field(default_factory=dict)
    calendar_result: list[CalendarDay] = field(default_factory=list)
    calendar_calls: int = 0

    async def search_subjects(
        self,
        keyword: str,
        limit: int = 5,
        offset: int = 0,
        subject_type: list[int] | None = None,
        subject_tags: list[str] | None = None,
    ) -> SearchSubjectsResponse:
        return self.search_result

    async def get_subject_details(self, subject_id: str) -> SubjectDetailsResponse:
        return self.subject_details.get(subject_id, {})

    async def get_subject_episodes(self, subject_id: int) -> EpisodeListResponse:
        return {"data": []}

    async def get_calendar(self) -> list[CalendarDay]:
        self.calendar_calls += 1
        return self.calendar_result


@dataclass
class FakeRenderConfig:
    rpc_url: str = "https://api.unitedpooh.top/rpc"
    max_retries: int = 1

    def get_render_server_url(self) -> str:
        return self.rpc_url

    def get_max_retries(self) -> int:
        return self.max_retries

    def get_render_mode(self) -> str:
        return "html"

    def get_episode_card_template(self) -> str:
        return "cinematic_poster"


@dataclass
class FakeSubjectRenderer:
    base64_result: list[str] = field(default_factory=list)

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
        return self.base64_result


@dataclass
class FakeCalendarRenderer:
    base64_result: str | None = "b64"
    calls: list[CalendarRenderCall] = field(default_factory=list)

    async def render_calendar(
        self,
        calendar_data: list[CalendarDay],
        rpc_url: str | None = None,
        headless: bool = True,
        max_retries: int = 3,
    ) -> str | None:
        self.calls.append(
            CalendarRenderCall(
                calendar_data=calendar_data, rpc_url=rpc_url, max_retries=max_retries
            )
        )
        return self.base64_result


@dataclass(frozen=True)
class CalendarRenderCall:
    calendar_data: list[CalendarDay]
    rpc_url: str | None
    max_retries: int


def _service(
    api: FakeBangumiApi | None = None,
    render_config: FakeRenderConfig | None = None,
    subject_renderer: FakeSubjectRenderer | None = None,
    calendar_renderer: FakeCalendarRenderer | None = None,
) -> SearchService:
    return SearchService(
        bangumi_api=api or FakeBangumiApi(),
        render_config=render_config or FakeRenderConfig(),
        subject_renderer=subject_renderer or FakeSubjectRenderer(),
        calendar_renderer=calendar_renderer or FakeCalendarRenderer(),
    )
