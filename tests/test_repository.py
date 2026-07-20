from __future__ import annotations

import sqlite3
from pathlib import Path

from astrbot_plugin_bangumi.src.db import BangumiRepository
from astrbot_plugin_bangumi.src.entities import BroadcastSchedule, Subject


def build_repository(tmp_path: Path) -> BangumiRepository:
    return BangumiRepository(str(tmp_path / "data" / "data.db"))


def sample_subject() -> Subject:
    return Subject(
        id=1,
        type=2,
        name="Sample",
        name_cn="示例",
        total_episodes=12,
        cover_url="https://example.com/cover.jpg",
    )


def test_subscription_baseline_and_delivery_are_per_session(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    subject = sample_subject()

    assert repository.subscribe("g1", subject, baseline_episode=3) is True
    assert repository.subscribe("g2", subject, baseline_episode=3) is True
    assert repository.pending_sessions("1", 3) == []
    assert repository.pending_sessions("1", 4) == ["g1", "g2"]

    repository.mark_notified("g1", "1", 4)

    assert repository.pending_sessions("1", 4) == ["g2"]
    assert repository.list_subscriptions("g1")[0].last_notified_episode == 4


def test_delivery_error_is_visible_and_cleared_after_success(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    repository.subscribe("g1", sample_subject(), baseline_episode=1)

    repository.mark_delivery_error("g1", "1", "send failed")
    assert repository.list_subscriptions("g1")[0].delivery_error == "send failed"

    repository.mark_notified("g1", "1", 2)
    assert repository.list_subscriptions("g1")[0].delivery_error is None


def test_broadcast_schedule_stores_date_weekday_and_time(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    repository.subscribe("g1", sample_subject(), baseline_episode=1)

    updated = repository.apply_broadcast_schedules(
        {
            "1": BroadcastSchedule(
                broadcast_date="2026-07-15",
                broadcast_time="23:30",
            )
        }
    )

    assert updated == 1
    status = repository.list_subscriptions("g1")[0]
    assert status.broadcast_date == "2026-07-15"
    assert status.broadcast_time == "23:30"
    assert status.broadcast_schedule == "首播 2026-07-15 · 每周三 23:30"


def test_find_and_unsubscribe_are_session_scoped(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    repository.subscribe("g1", sample_subject(), baseline_episode=0)
    repository.subscribe("g2", sample_subject(), baseline_episode=0)

    assert repository.find_subscription("g1", "示例")[0].subject_id == "1"
    assert repository.unsubscribe("g1", "1") is True
    assert repository.list_subscriptions("g1") == []
    assert len(repository.list_subscriptions("g2")) == 1


def test_legacy_session_is_merged_into_unified_origin(tmp_path: Path) -> None:
    repository = build_repository(tmp_path)
    subject = sample_subject()
    target = "aiocqhttp:GroupMessage:818800431"
    repository.subscribe("818800431", subject, baseline_episode=3)
    repository.mark_notified("818800431", "1", 5)
    repository.subscribe(target, subject, baseline_episode=4)

    migrated = repository.migrate_session_aliases(
        target,
        {"818800431", "aiocqhttp:group:818800431"},
    )

    assert migrated == 1
    assert repository.list_subscriptions("818800431") == []
    status = repository.list_subscriptions(target)[0]
    assert status.last_notified_episode == 5


def test_old_database_is_migrated_without_losing_progress(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "data.db"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE bangumi_subjects ("
            "subject_id VARCHAR PRIMARY KEY, name VARCHAR, air_date VARCHAR, "
            "total_episodes INTEGER, current_episode INTEGER, updated_at DATETIME)"
        )
        connection.execute(
            "CREATE TABLE subscriptions ("
            "group_id VARCHAR, subject_id VARCHAR, created_at DATETIME, "
            "PRIMARY KEY (group_id, subject_id))"
        )
        connection.execute(
            "INSERT INTO bangumi_subjects "
            "(subject_id, name, current_episode) VALUES ('1', 'Old', 5)"
        )
        connection.execute(
            "INSERT INTO subscriptions (group_id, subject_id) VALUES ('g1', '1')"
        )

    repository = BangumiRepository(str(db_path))

    assert repository.pending_sessions("1", 5) == []
    assert repository.pending_sessions("1", 6) == ["g1"]
    status = repository.list_subscriptions("g1")[0]
    assert status.last_notified_episode == 5
    assert status.current_episode == 5
    assert status.broadcast_date is None
