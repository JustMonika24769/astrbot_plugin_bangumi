"""
数据库 ORM 模型定义

此模块包含所有 SQLAlchemy ORM 模型,用于定义数据库表结构和关系

"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class BangumiSubject(Base):
    """
    番剧条目模型
    """

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

    def __repr__(self) -> str:
        return f"<BangumiSubject(id={self.subject_id}, name={self.name})>"

    def __str__(self) -> str:
        return f"{self.name} ({self.subject_id}) [{self.current_episode}/{self.total_episodes}]"


class Subscription(Base):
    """
    订阅关系模型
    """

    __tablename__ = "subscriptions"

    group_id = Column(String, primary_key=True)
    subject_id = Column(
        String, ForeignKey("bangumi_subjects.subject_id"), primary_key=True
    )
    created_at = Column(DateTime, default=func.now())

    # 建立与 BangumiSubject 的多对一关系
    subject = relationship("BangumiSubject", back_populates="subscriptions")

    def __repr__(self) -> str:
        return f"<Subscription(id={self.subject_id}, group_id={self.group_id}, created_at={self.created_at})>"

    def __str__(self) -> str:
        return f"- 群 {self.group_id} 订阅了 {self.subject.name} ({self.subject.subject_id})"
