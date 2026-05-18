from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from astrbot_plugin_bangumi.src.app.responses import AppImages, AppText
from astrbot_plugin_bangumi.src.app.search_service import SearchService
from astrbot_plugin_bangumi.src.domain.contracts import (
    CalendarDay,
    EpisodeListResponse,
    RenderData,
    SearchSubjectsResponse,
    SubjectDetailsResponse,
)
from astrbot_plugin_bangumi.src.domain.exceptions import BangumiApiError


@pytest.mark.asyncio
async def test_handle_subject_search_no_results() -> None:
    api = FakeBangumiApi(search_result={"data": []})
    service = _service(api=api)

    result = await service.handle_subject_search("none")

    assert result == AppText("🔍 未找到相关条目")


@pytest.mark.asyncio
async def test_prepare_subject_images_skips_missing_details_and_tolerates_episode_error() -> (
    None
):
    api = FakeBangumiApi(
        subject_details={"2": {"id": 2, "name": "ok"}},
        episode_results={2: BangumiApiError("episodes failed")},
    )
    subject_renderer = FakeSubjectRenderer(base64_result=["b64"])
    service = _service(api=api, subject_renderer=subject_renderer)

    images = await service._prepare_subject_images_base64(
        [{"id": 1}, {"id": 2}, {"name": "missing"}], top_k=3
    )

    assert images == ["b64"]
    assert api.subject_detail_calls == ["1", "2"]
    assert api.episode_calls == [2]
    assert subject_renderer.calls == [
        SubjectRenderCall(
            data_list=[{"id": 2, "name": "ok"}],
            rpc_url="https://api.unitedpooh.top/rpc",
            max_retries=1,
        )
    ]


@pytest.mark.asyncio
async def test_handle_calendar_render_failure() -> None:
    api = FakeBangumiApi(calendar_result=[{"weekday": {"id": 1}, "items": []}])
    calendar_renderer = FakeCalendarRenderer(base64_result=None)
    service = _service(api=api, calendar_renderer=calendar_renderer)

    result = await service.handle_calendar()

    assert result == AppText("❌ 图片生成失败")
    assert calendar_renderer.calls == [
        CalendarRenderCall(
            calendar_data=[{"weekday": {"id": 1}, "items": []}],
            rpc_url="https://api.unitedpooh.top/rpc",
            max_retries=1,
        )
    ]


@pytest.mark.asyncio
async def test_handle_today_success(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeBangumiApi(
        calendar_result=[
            {"weekday": {"id": 1}, "items": []},
            {"weekday": {"id": 2}, "items": [{"id": 1}]},
        ]
    )
    calendar_renderer = FakeCalendarRenderer(base64_result="b64")
    service = _service(api=api, calendar_renderer=calendar_renderer)
    monkeypatch.setattr(
        "astrbot_plugin_bangumi.src.app.search_service.datetime", _FakeDateTimeModule
    )

    result = await service.handle_today()

    assert result == AppImages(("b64",))
    assert calendar_renderer.calls == [
        CalendarRenderCall(
            calendar_data=[
                {"weekday": {"id": 2}, "items": [{"id": 1}], "is_today": True}
            ],
            rpc_url="https://api.unitedpooh.top/rpc",
            max_retries=1,
        )
    ]


@pytest.mark.asyncio
async def test_handle_today_no_matching_day(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeBangumiApi(calendar_result=[{"weekday": {"id": 1}, "items": []}])
    service = _service(api=api)
    monkeypatch.setattr(
        "astrbot_plugin_bangumi.src.app.search_service.datetime", _FakeDateTimeModule
    )

    result = await service.handle_today()

    assert result == AppText("❌ 未获取到今日放送数据")


EpisodeResult = EpisodeListResponse | Exception


@dataclass
class FakeBangumiApi:
    search_result: SearchSubjectsResponse = field(default_factory=lambda: {"data": []})
    subject_details: dict[str, SubjectDetailsResponse] = field(default_factory=dict)
    episode_results: dict[int, EpisodeResult] = field(default_factory=dict)
    calendar_result: list[CalendarDay] = field(default_factory=list)
    search_calls: list[SearchCall] = field(default_factory=list)
    subject_detail_calls: list[str] = field(default_factory=list)
    episode_calls: list[int] = field(default_factory=list)
    calendar_calls: int = 0

    async def search_subjects(
        self,
        keyword: str,
        limit: int = 5,
        offset: int = 0,
        subject_type: list[int] | None = None,
        subject_tags: list[str] | None = None,
    ) -> SearchSubjectsResponse:
        self.search_calls.append(
            SearchCall(
                keyword=keyword,
                limit=limit,
                offset=offset,
                subject_type=subject_type,
                subject_tags=subject_tags,
            )
        )
        return self.search_result

    async def get_subject_details(self, subject_id: str) -> SubjectDetailsResponse:
        self.subject_detail_calls.append(subject_id)
        return self.subject_details.get(subject_id, {})

    async def get_subject_episodes(self, subject_id: int) -> EpisodeListResponse:
        self.episode_calls.append(subject_id)
        result = self.episode_results.get(subject_id, {"data": []})
        if isinstance(result, Exception):
            raise result
        return result

    async def get_calendar(self) -> list[CalendarDay]:
        self.calendar_calls += 1
        return self.calendar_result


@dataclass(frozen=True)
class SearchCall:
    keyword: str
    limit: int
    offset: int
    subject_type: list[int] | None
    subject_tags: list[str] | None


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
    calls: list[SubjectRenderCall] = field(default_factory=list)

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
        self.calls.append(
            SubjectRenderCall(
                data_list=data_list, rpc_url=rpc_url, max_retries=max_retries
            )
        )
        return self.base64_result


@dataclass(frozen=True)
class SubjectRenderCall:
    data_list: list[RenderData]
    rpc_url: str | None
    max_retries: int


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


class _FakeDateTime:
    @classmethod
    def now(cls) -> _FakeDateTime:
        return cls()

    def isoweekday(self) -> int:
        return 2


class _FakeDateTimeModule:
    datetime = _FakeDateTime
