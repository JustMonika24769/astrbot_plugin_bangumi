from pathlib import Path

from astrbot_plugin_bangumi.src.db import BangumiRepository


def _build_repository(tmp_path: Path) -> BangumiRepository:
    return BangumiRepository(str(tmp_path / "data" / "bangumi.db"))


def test_repository_subscription_crud(tmp_path: Path) -> None:
    repository = _build_repository(tmp_path)

    assert repository.add_subscription("group_1", "1") is True
    assert repository.get_subscriptions("group_1") == ["1"]
    assert repository.get_subject_subscribers("1") == ["group_1"]
    assert repository.get_all_subscribed_groups() == ["group_1"]
    assert repository.remove_subscription("group_1", "1") is True
    assert repository.remove_subscription("group_1", "1") is False


def test_subscribe_subject_upserts_subject_and_is_idempotent(tmp_path: Path) -> None:
    repository = _build_repository(tmp_path)

    assert repository.subscribe_subject("group_1", "1", "旧名", "2024-01-01", 12)
    assert repository.subscribe_subject("group_1", "1", "新名", "2024-02-01", 24)

    subjects = repository.get_monitored_subjects()
    assert len(subjects) == 1
    assert str(subjects[0].name) == "新名"
    assert int(subjects[0].total_episodes) == 24
    assert repository.get_subscriptions("group_1") == ["1"]


def test_update_subject_ignores_none_values(tmp_path: Path) -> None:
    repository = _build_repository(tmp_path)

    repository.update_subject("1", name="初始", current_episode=1)
    repository.update_subject("1", name=None, current_episode=2)

    subject = repository.get_monitored_subjects()[0]
    assert str(subject.name) == "初始"
    assert int(subject.current_episode) == 2


def test_find_group_subscription_candidates_ranking_and_group_scope(
    tmp_path: Path,
) -> None:
    repository = _build_repository(tmp_path)
    repository.subscribe_subject("group_1", "123", "Alpha", "", 0)
    repository.subscribe_subject("group_1", "1234", "Alpha Extra", "", 0)
    repository.subscribe_subject("group_1", "2", "Beta Alpha", "", 0)
    repository.subscribe_subject("group_2", "999", "Alpha", "", 0)

    candidates = repository.find_group_subscription_candidates("group_1", "123")

    assert [str(subject.subject_id) for subject in candidates] == ["123", "1234"]
