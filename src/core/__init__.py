# src/api/__init__.py
from .subjects import SubjectsService
from .characters import CharactersService
from .persons import PersonsService       
from .users import UsersService           

# 聚合类：继承所有子Service的功能
class BangumiService(SubjectsService, CharactersService, PersonsService, UsersService):
    def __init__(self, access_token: str, user_agent: str, proxy: str | None = None):
        # 初始化最基础的父类 (BaseBangumiService)
        # 因为所有Service都继承自BaseBangumiService，super会自动处理MRO链
        super().__init__(access_token, user_agent, proxy)