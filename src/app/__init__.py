from importlib import import_module
from typing import Any

from .ports import (
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
from .responses import AppImages, AppResponse, AppText

__all__ = [
    "AppImages",
    "AppRenderMode",
    "AppResponse",
    "AppText",
    "BangumiApiPort",
    "CalendarRendererPort",
    "EpisodeRendererPort",
    "GroupNotifierPort",
    "LocalSubscriptionCandidateRecord",
    "MonitoredSubjectRecord",
    "RenderConfigPort",
    "SearchService",
    "SubjectRendererPort",
    "SubscriptionService",
    "SubscriptionStorePort",
]


def __getattr__(name: str) -> Any:
    if name == "SearchService":
        return import_module(".search_service", __name__).SearchService
    if name == "SubscriptionService":
        return import_module(".subscription_service", __name__).SubscriptionService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
