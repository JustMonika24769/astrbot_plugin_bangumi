import aiohttp

from .calendar import CalendarService
from .subjects import SubjectsService


class BangumiService(SubjectsService, CalendarService):
    def __init__(
        self,
        access_token: str,
        user_agent: str,
        proxy: str | None = None,
        max_retries: int = 3,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        # 初始化最基础的父类 (BaseBangumiService)
        # 因为所有Service都继承自BaseBangumiService,super会自动处理MRO链
        super().__init__(
            access_token,
            user_agent,
            proxy=proxy,
            max_retries=max_retries,
            session=session,
        )
