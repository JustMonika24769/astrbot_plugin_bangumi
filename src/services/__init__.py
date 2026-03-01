# src/api/__init__.py
from .calendar import CalendarService
from .subjects import SubjectsService


# 聚合类：继承所有子Service的功能
class BangumiService(SubjectsService, CalendarService):
    def __init__(self, access_token: str, user_agent: str, proxy: str | None = None):
        # 初始化最基础的父类 (BaseBangumiService)
        # 因为所有Service都继承自BaseBangumiService，super会自动处理MRO链
        super().__init__(access_token, user_agent, proxy)

    async def match_subscribable_subject(
        self, keyword: str
    ) -> tuple[str | None, dict | None]:
        """
        查找可订阅的番剧。
        流程：搜索 -> 获取详情 -> 检查每日放送列表
        返回: (错误信息, 番剧详情字典)
        如果是成功的，错误信息为 None，详情字典包含 id, name, air_date, total_episodes 等。

        """
        # 1. 搜索
        search_res = await self.search_subjects(
            keyword=keyword, subject_type=[2], subject_tags=None
        )
        if not search_res or "data" not in search_res or not search_res["data"]:
            return "🔍 未找到相关番剧", None

        target_subject = search_res["data"][0]
        subject_id = str(target_subject.get("id"))

        # 2. 详情
        details = await self.get_subject_details(subject_id)
        if not details:
            return "❌ 获取番剧详情失败", None

        name = details.get("name_cn") or details.get("name")

        # 3. 检查放送列表
        calendar_res = await self.get_calendar()
        is_in_calendar = False
        if calendar_res:
            for day_item in calendar_res:
                for item in day_item.get("items", []):
                    if str(item.get("id")) == subject_id:
                        is_in_calendar = True
                        break
                if is_in_calendar:
                    break

        if not is_in_calendar:
            return (
                f"⚠️ {name} 不在当前的每日放送列表中 (可能已完结或未开播)，暂不支持自动追踪。",
                None,
            )

        # 构造返回数据
        result_data = {
            "subject_id": subject_id,
            "name": name,
            "air_date": details.get("date", ""),
            "total_episodes": details.get("eps", 0),
        }
        return None, result_data
