from ..app import LocalSubscriptionCandidateRecord, MonitoredSubjectRecord
from ..db import BangumiRepository


class SqlAlchemySubscriptionStore:
    """把 SQLAlchemy repository 适配成应用层订阅存储端口。"""

    def __init__(self, repository: BangumiRepository) -> None:
        self._repository = repository

    def subscribe_subject(
        self,
        group_id: str,
        subject_id: str,
        name: str,
        air_date: str = "",
        total_episodes: int = 0,
    ) -> bool:
        return self._repository.subscribe_subject(
            group_id=group_id,
            subject_id=subject_id,
            name=name,
            air_date=air_date,
            total_episodes=total_episodes,
        )

    def remove_subscription(self, group_id: str, subject_id: str) -> bool:
        return self._repository.remove_subscription(group_id, subject_id)

    def find_group_subscription_candidates(
        self, group_id: str, keyword: str, limit: int = 5
    ) -> list[LocalSubscriptionCandidateRecord]:
        subjects = self._repository.find_group_subscription_candidates(
            group_id=group_id,
            keyword=keyword,
            limit=limit,
        )
        return [
            LocalSubscriptionCandidateRecord(
                subject_id=str(subject.subject_id),
                name=str(subject.name or ""),
            )
            for subject in subjects
        ]

    def get_monitored_subjects(self) -> list[MonitoredSubjectRecord]:
        subjects = self._repository.get_monitored_subjects()
        return [
            MonitoredSubjectRecord(
                subject_id=str(subject.subject_id),
                name=str(subject.name or "未知番剧"),
                current_episode=int(subject.current_episode or 0),
                air_date=str(subject.air_date or ""),
                total_episodes=int(subject.total_episodes or 0),
            )
            for subject in subjects
        ]

    def update_subject_episode(self, subject_id: str, new_episode: int) -> bool:
        return self._repository.update_subject_episode(subject_id, new_episode)

    def get_subject_subscribers(self, subject_id: str) -> list[str]:
        return self._repository.get_subject_subscribers(subject_id)
