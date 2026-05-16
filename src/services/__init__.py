from typing import Any

from ..api import (
    BangumiService,
    BaseBangumiService,
    CalendarService,
    CharactersService,
    PersonsService,
    SubjectsService,
    UsersService,
)
from ..app import SearchService, SubscriptionService
from ..domain import (
    BangumiApiError,
    BangumiRateLimitError,
    CalendarDay,
    CalendarItem,
    CalendarWeekday,
    CommonTag,
    DatabaseError,
    Episode,
    EpisodeItem,
    EpisodeListResponse,
    ImageSize,
    MessageResult,
    NoSubjectFound,
    PersonDetailsResponse,
    PersonsSearchResponse,
    PersonType,
    RenderData,
    SearchSubjectItem,
    SearchSubjectsResponse,
    SubjectDetailsResponse,
    SubjectType,
    SubscribeCandidate,
    SubscribeMatch,
    SubscriptionError,
    UnsubscribeMatch,
    UserDetailsResponse,
)

__all__ = [
    "BangumiApiError",
    "BangumiRateLimitError",
    "BangumiService",
    "BaseBangumiService",
    "CalendarDay",
    "CalendarItem",
    "CalendarService",
    "CalendarWeekday",
    "CharactersService",
    "CommonTag",
    "DatabaseError",
    "Episode",
    "EpisodeItem",
    "EpisodeListResponse",
    "ImageSize",
    "MessageResult",
    "NoSubjectFound",
    "PersonDetailsResponse",
    "PersonType",
    "PersonsSearchResponse",
    "PersonsService",
    "RenderData",
    "SearchService",
    "SearchSubjectItem",
    "SearchSubjectsResponse",
    "SubjectDetailsResponse",
    "SubjectType",
    "SubjectsService",
    "SubscribeCandidate",
    "SubscribeMatch",
    "SubscriptionError",
    "SubscriptionService",
    "UnsubscribeMatch",
    "UserDetailsResponse",
    "UsersService",
]

_COMPAT_EXPORTS: dict[str, Any] = {name: globals()[name] for name in __all__}


def __getattr__(name: str) -> Any:
    try:
        return _COMPAT_EXPORTS[name]
    except KeyError as e:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from e
