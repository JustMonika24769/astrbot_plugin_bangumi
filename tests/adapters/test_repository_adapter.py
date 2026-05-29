from types import SimpleNamespace
from unittest.mock import MagicMock

from astrbot_plugin_bangumi.src.adapters import SqlAlchemySubscriptionStore
from astrbot_plugin_bangumi.src.app import (
    LocalSubscriptionCandidateRecord,
    MonitoredSubjectRecord,
)


def test_repository_adapter_converts_local_subscription_candidates() -> None:
    repository = MagicMock()
    repository.find_group_subscription_candidates.return_value = [
        SimpleNamespace(subject_id=123, name="测试番剧")
    ]

    store = SqlAlchemySubscriptionStore(repository)

    assert store.find_group_subscription_candidates("group", "测") == [
        LocalSubscriptionCandidateRecord(subject_id="123", name="测试番剧")
    ]
    repository.find_group_subscription_candidates.assert_called_once_with(
        group_id="group",
        keyword="测",
        limit=5,
    )


def test_repository_adapter_converts_monitored_subjects() -> None:
    repository = MagicMock()
    repository.get_monitored_subjects.return_value = [
        SimpleNamespace(
            subject_id=123,
            name=None,
            current_episode=None,
            air_date=None,
            total_episodes=None,
        )
    ]

    store = SqlAlchemySubscriptionStore(repository)

    assert store.get_monitored_subjects() == [
        MonitoredSubjectRecord(
            subject_id="123",
            name="未知番剧",
            current_episode=0,
            air_date="",
            total_episodes=0,
        )
    ]
