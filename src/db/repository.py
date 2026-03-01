"""
数据访问层（Repository 模式）

此模块封装所有数据库操作，为业务层提供数据访问接口。

"""

import logging
import os

from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from sqlalchemy import create_engine
from sqlalchemy.orm import joinedload, scoped_session, sessionmaker

from .models import Base, BangumiSubject, Subscription

logger = logging.getLogger("astrbot")


class BangumiRepository:
    """
    番剧数据访问层
    """

    def __init__(self, db_path: str | None = None):
        """
        初始化数据访问层

        Args:
            db_path: 数据库文件路径，如果为 None 则使用默认路径
        """
        # 使用 AstrBot 提供的 API 获取数据目录
        data_dir = get_astrbot_data_path()
        # 按照需求构建路径: data/plugin_data/astrbot_plugin_bangumi
        plugin_data_dir = os.path.join(
            data_dir, "plugin_data", "astrbot_plugin_bangumi"
        )

        if not os.path.exists(plugin_data_dir):
            os.makedirs(plugin_data_dir)
        if db_path is None:
            self.db_path = os.path.join(plugin_data_dir, "data.db")
        else:
            self.db_path = db_path
        self._init_db()

    def _init_db(self):
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
            logger.error(f"初始化数据库失败: {e}")

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
            return False
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
                session.commit()

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
                session.commit()
            return True
        except Exception as e:
            logger.error(f"添加订阅失败: {e}")
            session.rollback()
            return False
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
            return False
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
            return []
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
            return []
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
            return []
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
            return []
        finally:
            session.close()
