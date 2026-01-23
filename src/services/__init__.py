# src/api/__init__.py
from .subjects import SubjectsService
from .calendar import CalendarService


# 聚合类：继承所有子Service的功能
class BangumiService(SubjectsService, CalendarService):
    def __init__(self, access_token: str, user_agent: str, proxy: str | None = None):
        # 初始化最基础的父类 (BaseBangumiService)
        # 因为所有Service都继承自BaseBangumiService，super会自动处理MRO链
        super().__init__(access_token, user_agent, proxy)
