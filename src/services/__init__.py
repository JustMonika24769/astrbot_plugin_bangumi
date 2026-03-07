from typing import TYPE_CHECKING, Any

import aiohttp

from .calendar import CalendarService
from .contracts import (
    CalendarDay,
    CalendarWeekday,
    EpisodeItem,
    MessageResult,
    RenderData,
)
from .exceptions import (
    BangumiApiError,
    BangumiRateLimitError,
    DatabaseError,
    NoSubjectFound,
    SubscriptionError,
)
from .schemas import Episode
from .subjects import SubjectsService
from .types import ImageSize, SubjectType

if TYPE_CHECKING:
    from .search import SearchService
    from .subscription import SubscriptionService


# 聚合类：继承所有子Service的功能
class BangumiService(SubjectsService, CalendarService):
    def __init__(
        self,
        access_token: str,
        user_agent: str,
        proxy: str | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        # 初始化最基础的父类 (BaseBangumiService)
        # 因为所有Service都继承自BaseBangumiService，super会自动处理MRO链
        super().__init__(access_token, user_agent, proxy, session=session)


def __getattr__(name: str) -> Any:
    if name == "SearchService":
        from .search import SearchService

        return SearchService
    if name == "SubscriptionService":
        from .subscription import SubscriptionService

        return SubscriptionService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BangumiApiError",
    "BangumiRateLimitError",
    "BangumiService",
    "CalendarDay",
    "CalendarService",
    "CalendarWeekday",
    "DatabaseError",
    "Episode",
    "EpisodeItem",
    "ImageSize",
    "MessageResult",
    "NoSubjectFound",
    "RenderData",
    "SearchService",
    "SubjectType",
    "SubjectsService",
    "SubscriptionError",
    "SubscriptionService",
]
