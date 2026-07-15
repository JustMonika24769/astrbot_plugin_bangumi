from __future__ import annotations

import os
from datetime import datetime
from difflib import SequenceMatcher

from astrbot.api import logger
from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from ..entities import Subject, SubscriptionView, TrackedSubject
from .models import BangumiSubject, Base, Subscription


class RepositoryError(RuntimeError):
    pass


class BangumiRepository:
    def __init__(self, db_path: str) -> None:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        try:
            self.engine = create_engine(f"sqlite:///{db_path}")
            Base.metadata.create_all(self.engine)
            self._migrate(self.engine)
            self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        except Exception as exc:
            raise RepositoryError(f"数据库初始化失败: {exc}") from exc

    @staticmethod
    def _migrate(engine: Engine) -> None:
        subject_columns = {
            "broadcast_time": "VARCHAR",
            "name_cn": "VARCHAR",
            "cover_url": "TEXT",
            "summary": "TEXT",
            "score": "FLOAT NOT NULL DEFAULT 0",
            "rank": "INTEGER NOT NULL DEFAULT 0",
            "last_checked_at": "DATETIME",
            "last_error": "TEXT",
        }
        subscription_columns = {
            "last_notified_episode": "INTEGER NOT NULL DEFAULT 0",
            "last_attempt_at": "DATETIME",
            "last_error": "TEXT",
        }
        try:
            inspector = inspect(engine)
            existing_subject = {
                column["name"] for column in inspector.get_columns("bangumi_subjects")
            }
            existing_subscription = {
                column["name"] for column in inspector.get_columns("subscriptions")
            }
            with engine.begin() as connection:
                for name, sql_type in subject_columns.items():
                    if name not in existing_subject:
                        connection.execute(
                            text(
                                f"ALTER TABLE bangumi_subjects ADD COLUMN {name} {sql_type}"
                            )
                        )
                added_delivery_progress = (
                    "last_notified_episode" not in existing_subscription
                )
                for name, sql_type in subscription_columns.items():
                    if name not in existing_subscription:
                        connection.execute(
                            text(
                                f"ALTER TABLE subscriptions ADD COLUMN {name} {sql_type}"
                            )
                        )
                if added_delivery_progress:
                    connection.execute(
                        text(
                            "UPDATE subscriptions "
                            "SET last_notified_episode = COALESCE(("
                            "SELECT current_episode FROM bangumi_subjects "
                            "WHERE bangumi_subjects.subject_id = subscriptions.subject_id"
                            "), 0)"
                        )
                    )
        except Exception as exc:
            raise RepositoryError(f"数据库迁移失败: {exc}") from exc

    @staticmethod
    def _apply_subject(row: BangumiSubject, subject: Subject) -> None:
        row.name = subject.name
        row.name_cn = subject.name_cn
        row.cover_url = subject.cover_url
        row.summary = subject.summary
        row.score = subject.score
        row.rank = subject.rank
        row.air_date = subject.air_date
        row.total_episodes = subject.total_episodes

    def upsert_subject(
        self, subject: Subject, *, current_episode: int | None = None
    ) -> None:
        with self.Session.begin() as session:
            row = session.get(BangumiSubject, str(subject.id))
            if row is None:
                row = BangumiSubject(subject_id=str(subject.id))
                session.add(row)
            self._apply_subject(row, subject)
            if current_episode is not None:
                row.current_episode = max(
                    int(row.current_episode or 0), int(current_episode)
                )

    def subscribe(
        self,
        session_id: str,
        subject: Subject,
        *,
        baseline_episode: int,
        broadcast_time: str | None = None,
    ) -> bool:
        try:
            with self.Session.begin() as session:
                subject_id = str(subject.id)
                row = session.get(BangumiSubject, subject_id)
                if row is None:
                    row = BangumiSubject(subject_id=subject_id)
                    session.add(row)
                self._apply_subject(row, subject)
                row.current_episode = max(
                    int(row.current_episode or 0), int(baseline_episode)
                )
                if broadcast_time and not row.broadcast_time:
                    row.broadcast_time = broadcast_time

                key = {"group_id": session_id, "subject_id": subject_id}
                existing = session.get(Subscription, key)
                if existing is not None:
                    return False
                session.add(
                    Subscription(
                        group_id=session_id,
                        subject_id=subject_id,
                        last_notified_episode=int(baseline_episode),
                    )
                )
                return True
        except Exception as exc:
            raise RepositoryError(f"保存订阅失败: {exc}") from exc

    def unsubscribe(self, session_id: str, subject_id: str) -> bool:
        try:
            with self.Session.begin() as session:
                key = {"group_id": session_id, "subject_id": str(subject_id)}
                subscription = session.get(Subscription, key)
                if subscription is None:
                    return False
                session.delete(subscription)
                session.flush()
                remaining = session.scalar(
                    select(Subscription).where(
                        Subscription.subject_id == str(subject_id)
                    )
                )
                if remaining is None:
                    subject = session.get(BangumiSubject, str(subject_id))
                    if subject is not None:
                        session.delete(subject)
                return True
        except Exception as exc:
            raise RepositoryError(f"取消订阅失败: {exc}") from exc

    def migrate_session_aliases(
        self, target_session_id: str, aliases: set[str]
    ) -> int:
        normalized_aliases = {
            alias.strip()
            for alias in aliases
            if alias.strip() and alias.strip() != target_session_id
        }
        if not normalized_aliases:
            return 0
        try:
            with self.Session.begin() as session:
                sources = session.scalars(
                    select(Subscription).where(
                        Subscription.group_id.in_(normalized_aliases)
                    )
                ).all()
                migrated = 0
                for source in sources:
                    key = {
                        "group_id": target_session_id,
                        "subject_id": source.subject_id,
                    }
                    target = session.get(Subscription, key)
                    if target is None:
                        target = Subscription(
                            group_id=target_session_id,
                            subject_id=source.subject_id,
                            last_notified_episode=int(
                                source.last_notified_episode or 0
                            ),
                            last_attempt_at=source.last_attempt_at,
                            last_error=source.last_error,
                            created_at=source.created_at,
                        )
                        session.add(target)
                        session.flush()
                    else:
                        source_progress = int(source.last_notified_episode or 0)
                        target_progress = int(target.last_notified_episode or 0)
                        if source_progress > target_progress:
                            target.last_notified_episode = source_progress
                            target.last_attempt_at = source.last_attempt_at
                            target.last_error = source.last_error
                        if source.created_at and (
                            not target.created_at
                            or source.created_at < target.created_at
                        ):
                            target.created_at = source.created_at
                    session.delete(source)
                    migrated += 1
                return migrated
        except Exception as exc:
            raise RepositoryError(f"迁移旧会话订阅失败: {exc}") from exc

    def list_tracked_subjects(
        self, *, session_id: str | None = None
    ) -> list[TrackedSubject]:
        try:
            with self.Session() as session:
                statement = select(BangumiSubject).join(Subscription).distinct()
                if session_id is not None:
                    statement = statement.where(Subscription.group_id == session_id)
                rows = session.scalars(
                    statement.order_by(BangumiSubject.subject_id)
                ).all()
                return [self._tracked(row) for row in rows]
        except Exception as exc:
            raise RepositoryError(f"读取追番条目失败: {exc}") from exc

    def list_subscriptions(self, session_id: str) -> list[SubscriptionView]:
        try:
            with self.Session() as session:
                rows = session.execute(
                    select(Subscription, BangumiSubject)
                    .join(
                        BangumiSubject,
                        BangumiSubject.subject_id == Subscription.subject_id,
                    )
                    .where(Subscription.group_id == session_id)
                    .order_by(BangumiSubject.name_cn, BangumiSubject.name)
                ).all()
                return [
                    self._subscription(subscription, subject)
                    for subscription, subject in rows
                ]
        except Exception as exc:
            raise RepositoryError(f"读取订阅列表失败: {exc}") from exc

    def find_subscription(self, session_id: str, query: str) -> list[SubscriptionView]:
        normalized = query.strip().lower()
        if not normalized:
            return []
        rows = self.list_subscriptions(session_id)

        def score(item: SubscriptionView) -> tuple[int, int, float, str]:
            title = item.title.lower()
            return (
                int(item.subject_id == normalized),
                int(normalized in title or item.subject_id.startswith(normalized)),
                SequenceMatcher(None, normalized, title).ratio(),
                item.subject_id,
            )

        matches = [
            item
            for item in rows
            if item.subject_id == normalized
            or item.subject_id.startswith(normalized)
            or normalized in item.title.lower()
            or SequenceMatcher(None, normalized, item.title.lower()).ratio() >= 0.35
        ]
        return sorted(matches, key=score, reverse=True)

    def pending_sessions(self, subject_id: str, episode: int) -> list[str]:
        try:
            with self.Session() as session:
                rows = session.scalars(
                    select(Subscription).where(
                        Subscription.subject_id == str(subject_id),
                        Subscription.last_notified_episode < int(episode),
                    )
                ).all()
                return [str(row.group_id) for row in rows]
        except Exception as exc:
            raise RepositoryError(f"读取待通知会话失败: {exc}") from exc

    def delivery_progress(
        self, subject_id: str, session_ids: list[str]
    ) -> dict[str, int]:
        if not session_ids:
            return {}
        try:
            with self.Session() as session:
                rows = session.scalars(
                    select(Subscription).where(
                        Subscription.subject_id == str(subject_id),
                        Subscription.group_id.in_(session_ids),
                    )
                ).all()
                return {
                    str(row.group_id): int(row.last_notified_episode or 0)
                    for row in rows
                }
        except Exception as exc:
            raise RepositoryError(f"读取通知进度失败: {exc}") from exc

    def mark_notified(self, session_id: str, subject_id: str, episode: int) -> None:
        try:
            with self.Session.begin() as session:
                subscription = session.get(
                    Subscription,
                    {"group_id": session_id, "subject_id": str(subject_id)},
                )
                if subscription is None:
                    raise RepositoryError("订阅关系不存在")
                subscription.last_notified_episode = max(
                    int(subscription.last_notified_episode or 0), int(episode)
                )
                subscription.last_attempt_at = datetime.now()
                subscription.last_error = None
        except RepositoryError:
            raise
        except Exception as exc:
            raise RepositoryError(f"更新通知进度失败: {exc}") from exc

    def mark_delivery_error(self, session_id: str, subject_id: str, error: str) -> None:
        try:
            with self.Session.begin() as session:
                subscription = session.get(
                    Subscription,
                    {"group_id": session_id, "subject_id": str(subject_id)},
                )
                if subscription is not None:
                    subscription.last_attempt_at = datetime.now()
                    subscription.last_error = error[:1000]
        except Exception as exc:
            logger.error(f"记录通知错误失败: {exc}")

    def mark_checked(
        self,
        subject_id: str,
        *,
        current_episode: int | None = None,
        error: str | None = None,
    ) -> None:
        try:
            with self.Session.begin() as session:
                subject = session.get(BangumiSubject, str(subject_id))
                if subject is None:
                    return
                if current_episode is not None:
                    subject.current_episode = max(
                        int(subject.current_episode or 0), int(current_episode)
                    )
                subject.last_checked_at = datetime.now()
                subject.last_error = error[:1000] if error else None
        except Exception as exc:
            raise RepositoryError(f"记录检查状态失败: {exc}") from exc

    def set_broadcast_time(self, subject_id: str, value: str | None) -> bool:
        try:
            with self.Session.begin() as session:
                subject = session.get(BangumiSubject, str(subject_id))
                if subject is None:
                    return False
                subject.broadcast_time = value
                return True
        except Exception as exc:
            raise RepositoryError(f"设置放送时间失败: {exc}") from exc

    def apply_broadcast_times(self, mapping: dict[str, str]) -> int:
        if not mapping:
            return 0
        updated = 0
        try:
            with self.Session.begin() as session:
                rows = session.scalars(
                    select(BangumiSubject).where(
                        BangumiSubject.subject_id.in_(list(mapping))
                    )
                ).all()
                for row in rows:
                    if not row.broadcast_time and row.subject_id in mapping:
                        row.broadcast_time = mapping[row.subject_id]
                        updated += 1
            return updated
        except Exception as exc:
            raise RepositoryError(f"更新放送时间失败: {exc}") from exc

    @staticmethod
    def _tracked(row: BangumiSubject) -> TrackedSubject:
        return TrackedSubject(
            subject_id=str(row.subject_id),
            title=str(row.name_cn or row.name or f"条目 {row.subject_id}"),
            name=str(row.name or ""),
            cover_url=str(row.cover_url or ""),
            air_date=str(row.air_date or ""),
            total_episodes=int(row.total_episodes or 0),
            current_episode=int(row.current_episode or 0),
            broadcast_time=str(row.broadcast_time) if row.broadcast_time else None,
            last_checked_at=(
                row.last_checked_at.isoformat(timespec="seconds")
                if row.last_checked_at
                else None
            ),
            last_error=str(row.last_error) if row.last_error else None,
        )

    @staticmethod
    def _subscription(
        subscription: Subscription, subject: BangumiSubject
    ) -> SubscriptionView:
        return SubscriptionView(
            session_id=str(subscription.group_id),
            subject_id=str(subject.subject_id),
            title=str(subject.name_cn or subject.name or f"条目 {subject.subject_id}"),
            cover_url=str(subject.cover_url or ""),
            total_episodes=int(subject.total_episodes or 0),
            current_episode=int(subject.current_episode or 0),
            last_notified_episode=int(subscription.last_notified_episode or 0),
            broadcast_time=(
                str(subject.broadcast_time) if subject.broadcast_time else None
            ),
            last_checked_at=(
                subject.last_checked_at.isoformat(timespec="seconds")
                if subject.last_checked_at
                else None
            ),
            subject_error=str(subject.last_error) if subject.last_error else None,
            delivery_error=(
                str(subscription.last_error) if subscription.last_error else None
            ),
        )
