"""
APScheduler 管理器

此模块提供了一个使用指定时区的 APScheduler 生命周期管理器
"""

from collections.abc import Callable

import pytz
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from astrbot.api import logger


class SchedulerManager:
    """
    APScheduler 的管理器类
    它使用 Asia/Shanghai 时区初始化调度器,并提供添加、删除和管理任务的方法
    """

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone=pytz.timezone("Asia/Shanghai"))
        self.scheduler.start()
        logger.info("调度器已初始化并在 Asia/Shanghai 时区启动.")

    def add_job(
        self, func: Callable[..., object], trigger: str, **kwargs: object
    ) -> str | None:
        """
        向调度器添加一个任务

        Args:
            func (Callable): 要执行的异步函数
            trigger (str): 触发器类型(例如:'interval'、'cron'、'date')
            **kwargs: 触发器的参数(例如:seconds=30, hour=8, minute=0)

        Returns:
            str | None: 添加的任务ID,如果失败则返回 None
        """
        try:
            job = self.scheduler.add_job(func, trigger, **kwargs)
            return str(job.id)
        except (RuntimeError, ValueError, TypeError) as e:
            logger.error(f"Error adding job: {e}")
            return None

    def cancel_job(self, job_id: str) -> None:
        """
        根据任务ID取消任务

        Args:
            job_id (str): 要取消的任务的ID
        """
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"定时任务{job_id}已取消.")
        except JobLookupError:
            logger.warning(f"未找到定时任务{job_id}")
        except (RuntimeError, ValueError, TypeError) as e:
            logger.error(f"取消任务失败{job_id}: {e}")

    def shutdown(self, wait: bool = False) -> None:
        """
        关闭调度器
        """
        if self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            logger.info("调度器已关闭.")
