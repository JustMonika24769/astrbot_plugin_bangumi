import logging
import os

from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    create_engine,
    func,
)
from sqlalchemy.orm import (
    sessionmaker,
    declarative_base,
    scoped_session,
    relationship,
    joinedload,
)

logger = logging.getLogger("astrbot")

Base = declarative_base()


class BangumiSubject(Base):
    __tablename__ = "bangumi_subjects"

    subject_id = Column(String, primary_key=True)
    name = Column(String)
    air_date = Column(String)  # 开播日期/时间
    total_episodes = Column(Integer, default=0)
    current_episode = Column(Integer, default=0)  # 当前已更新/已通知集数
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # 建立与 Subscription 的一对多关系
    subscriptions = relationship(
        "Subscription", back_populates="subject", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<BangumiSubject(id={self.subject_id}, name={self.name})>"


class Subscription(Base):
    __tablename__ = "subscriptions"

    group_id = Column(String, primary_key=True)
    subject_id = Column(
        String, ForeignKey("bangumi_subjects.subject_id"), primary_key=True
    )
    created_at = Column(DateTime, default=func.now())

    # 建立与 BangumiSubject 的多对一关系
    subject = relationship("BangumiSubject", back_populates="subscriptions")


class StorageManager:
    def __init__(self, db_path: str | None = None):
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
        try:
            # 使用 sqlite
            engine = create_engine(f"sqlite:///{self.db_path}")
            # 创建表
            Base.metadata.create_all(engine)
            # 创建 session factory
            self.Session = scoped_session(sessionmaker(bind=engine))
        except Exception as e:
            logger.error(f"初始化数据库失败: {e}")

    def update_subject(self, subject_id: str, **kwargs):
        """更新或保存番剧信息。支持传入 name, air_date, total_episodes, current_episode 等。"""
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
        """添加订阅 (若 Subject 不存在则创建占位)"""
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

    def get_subscriptions(self, group_id: str) -> list[str]:
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
        """获取所有已订阅的番剧列表，用于轮询更新"""
        session = self.Session()
        try:
            # 也可以根据是否有订阅者来过滤
            subjects = session.query(BangumiSubject).all()
            # session.expunge_all() # 使得对象可以在 session 关闭后访问 (Lazy loading 会失效)
            # 或者返回 ID 列表，或者保持 session 范围。
            # 这里为了简单，返回查询结果，调用者需注意 session 生命周期。
            # 但因为使用了 scoped_session，且 finally remove() 了，直接返回对象可能会导致 DetachedInstanceError 如果访问 lazy 属性。
            # 解决方案：Eager load subscriptions
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

    def update_subject_episode(self, subject_id: str, new_episode: int):
        """更新番剧最新集数 (快捷方法)"""
        return self.update_subject(subject_id, current_episode=new_episode)

    def get_subject_subscribers(self, subject_id: str) -> list[str]:
        """获取订阅了某番剧的所有群组ID"""
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
