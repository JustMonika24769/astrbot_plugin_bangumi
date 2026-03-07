"""
数据访问层（Repository 模式）

此模块封装所有数据库操作，为业务层提供数据访问接口。

"""

import os
from difflib import SequenceMatcher

from astrbot.api import logger
from sqlalchemy import create_engine, or_
from sqlalchemy.orm import joinedload, scoped_session, sessionmaker

from ..services import DatabaseError
from .models import BangumiSubject, Base, Subscription


class BangumiRepository:
    """
    番剧数据访问层
    """

    def __init__(self, db_path: str) -> None:
        """
        初始化数据访问层

        Args:
            db_path: 数据库文件路径
        """
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """
        初始化数据库连接和表结构
        """
        try:
            # 使用 sqlite
            engine = create_engine(f"sqlite:///{self.db_path}")
            # 创建表
            Base.metadata.create_all(engine)
            # 创建 session factory
            self.Session = scoped_session(sessionmaker(bind=engine))
        except Exception as e:
            raise DatabaseError(f"初始化数据库失败: {e}") from e

    def update_subject(self, subject_id: str, **kwargs) -> bool:
        """
        更新或保存番剧信息

        Args:
            subject_id: 番剧 ID
            **kwargs: 支持传入 name, air_date, total_episodes, current_episode 等

        Returns:
            操作是否成功

        """
        session = self.Session()
        try:
            subject = (
                session.query(BangumiSubject)
                .filter_by(subject_id=str(subject_id))
                .first()
            )
            if not subject:
                name = kwargs.pop("name", "未知番剧")
                subject = BangumiSubject(
                    subject_id=str(subject_id), name=name, **kwargs
                )
                session.add(subject)
            else:
                for key, value in kwargs.items():
                    if hasattr(subject, key) and value is not None:
                        setattr(subject, key, value)
            session.commit()
            return True
        except Exception as e:
            logger.error(f"更新番剧信息失败: {e}")
            session.rollback()
            raise DatabaseError(f"更新番剧信息失败: {e}") from e
        finally:
            session.close()

    def add_subscription(self, group_id: str, subject_id: str) -> bool:
        """
        添加订阅关系

        Args:
            group_id: 群组 ID
            subject_id: 番剧 ID

        Returns:
            操作是否成功

        """
        session = self.Session()
        try:
            # 确保 Subject 存在
            subject = (
                session.query(BangumiSubject)
                .filter_by(subject_id=str(subject_id))
                .first()
            )
            if not subject:
                subject = BangumiSubject(subject_id=str(subject_id), name="未知番剧")
                session.add(subject)

            existing = (
                session.query(Subscription)
                .filter_by(group_id=str(group_id), subject_id=str(subject_id))
                .first()
            )

            if not existing:
                new_sub = Subscription(
                    group_id=str(group_id), subject_id=str(subject_id)
                )
                session.add(new_sub)

            session.commit()  # 单次 commit，保证原子性
            return True
        except Exception as e:
            logger.error(f"添加订阅失败: {e}")
            session.rollback()
            raise DatabaseError(f"添加订阅失败: {e}") from e
        finally:
            session.close()

    def remove_subscription(self, group_id: str, subject_id: str) -> bool:
        """
        移除订阅关系

        Args:
            group_id: 群组 ID
            subject_id: 番剧 ID

        Returns:
            操作是否成功

        """
        session = self.Session()
        try:
            sub = (
                session.query(Subscription)
                .filter_by(group_id=str(group_id), subject_id=str(subject_id))
                .first()
            )
            if sub:
                session.delete(sub)
                session.commit()
                return True
            return False  # 订阅不存在
        except Exception as e:
            logger.error(f"移除订阅失败: {e}")
            session.rollback()
            raise DatabaseError(f"移除订阅失败: {e}") from e
        finally:
            session.close()

    def get_subscriptions(self, group_id: str) -> list[str]:
        """
        获取指定群组的所有订阅

        Args:
            group_id: 群组 ID

        Returns:
            订阅的番剧 ID 列表

        """
        session = self.Session()
        try:
            subs = session.query(Subscription).filter_by(group_id=str(group_id)).all()
            return [sub.subject_id for sub in subs]
        except Exception as e:
            logger.error(f"获取订阅失败: {e}")
            raise DatabaseError(f"获取订阅失败: {e}") from e
        finally:
            session.close()

    def get_monitored_subjects(self) -> list[BangumiSubject]:
        """
        获取所有已订阅的番剧列表，用于轮询更新

        Returns:
            番剧对象列表

        """
        session = self.Session()
        try:
            # Eager load subscriptions 避免 DetachedInstanceError
            subjects = (
                session.query(BangumiSubject)
                .options(joinedload(BangumiSubject.subscriptions))
                .all()
            )
            return subjects
        except Exception as e:
            logger.error(f"获取监控番剧失败: {e}")
            raise DatabaseError(f"获取监控番剧失败: {e}") from e
        finally:
            session.close()

    def update_subject_episode(self, subject_id: str, new_episode: int) -> bool:
        """
        更新番剧最新集数（快捷方法）

        Args:
            subject_id: 番剧 ID
            new_episode: 新的集数

        Returns:
            操作是否成功

        """
        return self.update_subject(subject_id, current_episode=new_episode)

    def subscribe_subject(
        self,
        group_id: str,
        subject_id: str,
        name: str,
        air_date: str = "",
        total_episodes: int = 0,
    ) -> bool:
        """
        原子性地 upsert 番剧信息并建立订阅关系。

        将 update_subject + add_subscription 合并到单一事务中，
        避免两次独立调用之间发生异常导致脏数据。

        Args:
            group_id: 群组 ID
            subject_id: 番剧 ID
            name: 番剧名称
            air_date: 开播日期
            total_episodes: 总集数

        Returns:
            操作是否成功
        """
        session = self.Session()
        try:
            # 1. upsert BangumiSubject
            subject = (
                session.query(BangumiSubject)
                .filter_by(subject_id=str(subject_id))
                .first()
            )
            if not subject:
                subject = BangumiSubject(
                    subject_id=str(subject_id),
                    name=name,
                    air_date=air_date,
                    total_episodes=total_episodes,
                )
                session.add(subject)
            else:
                subject.name = name
                if air_date:
                    subject.air_date = air_date
                if total_episodes:
                    subject.total_episodes = total_episodes

            # 2. 添加订阅关系（若不存在）
            existing = (
                session.query(Subscription)
                .filter_by(group_id=str(group_id), subject_id=str(subject_id))
                .first()
            )
            if not existing:
                session.add(
                    Subscription(group_id=str(group_id), subject_id=str(subject_id))
                )

            # 3. 单次 commit，保证 subject 与 subscription 同时成功或同时回滚
            session.commit()
            return True
        except Exception as e:
            logger.error(f"原子订阅失败: {e}")
            session.rollback()
            raise DatabaseError(f"原子订阅失败: {e}") from e
        finally:
            session.close()

    def get_subject_subscribers(self, subject_id: str) -> list[str]:
        """
        获取订阅了某番剧的所有群组 ID

        Args:
            subject_id: 番剧 ID

        Returns:
            群组 ID 列表

        """
        session = self.Session()
        try:
            subs = (
                session.query(Subscription).filter_by(subject_id=str(subject_id)).all()
            )
            return [sub.group_id for sub in subs]
        except Exception as e:
            logger.error(f"获取订阅群组失败: {e}")
            raise DatabaseError(f"获取订阅群组失败: {e}") from e
        finally:
            session.close()

    def get_all_subscribed_groups(self) -> list[str]:
        """
        获取所有拥有订阅的群组 ID

        Returns:
            群组 ID 列表

        """
        session = self.Session()
        try:
            groups = session.query(Subscription.group_id).distinct().all()
            return [g[0] for g in groups]
        except Exception as e:
            logger.error(f"获取所有订阅群组失败: {e}")
            raise DatabaseError(f"获取所有订阅群组失败: {e}") from e
        finally:
            session.close()

    def find_group_subscription_candidates(
        self, group_id: str, keyword: str, limit: int = 5
    ) -> list[BangumiSubject]:
        """
        在指定群组的订阅中查找与关键词匹配的番剧候选。

        匹配优先级：
        1. subject_id 精确匹配
        2. subject_id 前缀匹配
        3. name 包含匹配（忽略大小写）
        4. name 相似度（SequenceMatcher）
        """
        session = self.Session()
        try:
            normalized_keyword = str(keyword).strip()
            if not normalized_keyword:
                return []

            keyword_lower = normalized_keyword.lower()
            search_pattern = f"%{normalized_keyword}%"

            candidates = (
                session.query(BangumiSubject)
                .join(
                    Subscription, Subscription.subject_id == BangumiSubject.subject_id
                )
                .filter(Subscription.group_id == str(group_id))
                .filter(
                    or_(
                        BangumiSubject.subject_id == normalized_keyword,
                        BangumiSubject.subject_id.like(f"{normalized_keyword}%"),
                        BangumiSubject.name.ilike(search_pattern),
                    )
                )
                .all()
            )

            def score(subject: BangumiSubject) -> tuple[int, int, int, float, str]:
                subject_id = str(subject.subject_id or "")
                name = str(subject.name or "")
                name_lower = name.lower()
                exact_id = int(subject_id == normalized_keyword)
                prefix_id = int(subject_id.startswith(normalized_keyword))
                name_contains = int(keyword_lower in name_lower)
                similarity = SequenceMatcher(None, keyword_lower, name_lower).ratio()
                return (exact_id, prefix_id, name_contains, similarity, subject_id)

            sorted_candidates = sorted(
                candidates,
                key=lambda subject: (
                    -score(subject)[0],
                    -score(subject)[1],
                    -score(subject)[2],
                    -score(subject)[3],
                    score(subject)[4],
                ),
            )
            return sorted_candidates[:limit]
        except Exception as e:
            logger.error(f"查询群组订阅候选失败: {e}")
            raise DatabaseError(f"查询群组订阅候选失败: {e}") from e
        finally:
            session.close()
