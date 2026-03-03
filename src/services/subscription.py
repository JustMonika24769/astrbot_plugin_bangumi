import asyncio
import aiohttp
from typing import Optional, List, Tuple, Dict, Any
from astrbot.api import logger
from astrbot.api.star import StarTools
from astrbot.core.message.message_event_result import MessageChain

from ..db.repository import BangumiRepository
from . import BangumiService
from .schemas import Episode
from .types import ImageSize
from ..config.config_manager import ConfigManager
from ..render.episode_renderer import EpisodeRenderer


class SubscriptionService:
    def __init__(
        self,
        repository: BangumiRepository,
        service: BangumiService,
        config_manager: ConfigManager,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self.storage = repository
        self.service = service
        self.config_manager = config_manager
        self.renderer = EpisodeRenderer(session=session)

    async def _match_subscribable_subject(
        self, keyword: str
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        查找可订阅的番剧逻辑（从 API 层迁移至此）。
        """
        # 1. 搜索
        search_res = await self.service.search_subjects(
            keyword=keyword, subject_type=[2], subject_tags=None
        )
        if not search_res or "data" not in search_res or not search_res["data"]:
            return "🔍 未找到相关番剧", None

        target_subject = search_res["data"][0]
        subject_id = str(target_subject.get("id"))

        # 2. 详情
        details = await self.service.get_subject_details(subject_id)
        if not details:
            return "❌ 获取番剧详情失败", None

        name = details.get("name_cn") or details.get("name")

        # 3. 检查放送列表
        calendar_res = await self.service.get_calendar()
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

    async def subscribe(self, group_id: str, query: str) -> str:
        """
        处理订阅逻辑：匹配条目 -> 存入数据库 -> 建立订阅关系。
        """
        logger.info(f"处理追番请求: {query}, group_id={group_id}")
        try:
            # 1. 匹配条目 (调用内部迁移后的逻辑)
            error_msg, subject_info = await self._match_subscribable_subject(query)
            if error_msg:
                return error_msg
            if not subject_info:
                return "❌ 未知错误：未能获取番剧信息"

            subject_id = subject_info["subject_id"]
            name = subject_info["name"]

            # 2. 更新/存入条目基础信息
            self.storage.update_subject(
                subject_id=subject_id,
                name=name,
                air_date=subject_info["air_date"],
                total_episodes=subject_info["total_episodes"],
            )

            # 3. 添加订阅关系
            success = self.storage.add_subscription(group_id, subject_id)
            if success:
                return f"✅ 成功订阅《{name}》！\n如有更新将推送到本群。"
            else:
                return "❌ 订阅失败，数据库错误。"
        except Exception as e:
            logger.error(f"SubscriptionService.subscribe 失败: {e}")
            return f"❌ 处理失败: {e}"

    async def unsubscribe(self, group_id: str, query: str) -> str:
        """
        取消订阅逻辑。
        """
        logger.info(f"处理取消追番请求: {query}, group_id={group_id}")
        try:
            error_msg, subject_info = await self._match_subscribable_subject(query)
            if error_msg:
                return error_msg
            if not subject_info:
                return "❌ 未知错误：未能获取番剧信息"

            subject_id = subject_info["subject_id"]
            name = subject_info["name"]

            success = self.storage.remove_subscription(group_id, subject_id)
            if success:
                return f"✅ 已成功取消订阅《{name}》。"
            else:
                return f"❌ 取消订阅失败：你可能并没有订阅《{name}》。"
        except Exception as e:
            logger.error(f"SubscriptionService.unsubscribe 失败: {e}")
            return f"❌ 处理失败: {e}"

    async def check_updates(self):
        """
        定时任务核心逻辑：检查所有监控中的番剧是否有更新。
        """
        subjects = self.storage.get_monitored_subjects()
        logger.info(f"开始更新 {len(subjects)} 个番剧的集数信息")

        for subject in subjects:
            try:
                # 获取最新集数
                latest_episode = await self.service.get_latest_episode(
                    int(subject.subject_id)
                )
                if not latest_episode:
                    continue

                # 尝试获取封面图用于渲染
                try:
                    image_base64 = await self.service.get_subject_base64image(
                        subject.subject_id, size=ImageSize.LARGE
                    )
                    if image_base64:
                        latest_episode.image_url = (
                            f"data:image/png;base64,{image_base64}"
                        )
                except Exception as e:
                    logger.error(f"获取条目 {subject.name} 图片失败: {e}")

                # 比对更新
                if latest_episode.ep > subject.current_episode:
                    logger.info(f"番剧《{subject.name}》有更新: {subject.current_episode} -> {latest_episode.ep}")

                    # 更新数据库
                    # 显式转换为 str 以解决 Pylance 对 SQLAlchemy Column 对象的类型报错
                    self.storage.update_subject_episode(str(subject.subject_id), latest_episode.ep)

                    # 发送通知
                    await self._notify_subscribers(latest_episode, str(subject.subject_id), str(subject.name))

            except Exception as e:
                logger.error(f"更新番剧《{subject.name}》失败: {e}")

    async def _notify_subscribers(
        self, episode: Episode, subject_id: str, subject_name: str
    ) -> None:
        """
        渲染并发送更新通知。
        """
        subscribed_groups = self.storage.get_subject_subscribers(subject_id)
        if not subscribed_groups:
            return

        # 渲染图片
        base64_image = await self.renderer.render_episode(
            episode,
            rpc_url=self.config_manager.get_render_server_url(),
            max_retries=self.config_manager.get_max_retries(),
        )

        chain = MessageChain()
        if base64_image:
            chain = chain.base64_image(base64_image)
        else:
            # 如果图片渲染失败，发送纯文本通知作为兜底
            chain = chain.message(
                f"🔔 番剧《{subject_name}》更新啦！\n第 {episode.ep} 集：{episode.name_cn or episode.name}"
            )

        for group_id in subscribed_groups:
            try:
                await StarTools.send_message_by_id(
                    type="GroupMessage", id=group_id, message_chain=chain
                )
                logger.info(f"向群组 {group_id} 发送《{subject_name}》更新通知成功。")
            except Exception as e:
                logger.error(
                    f"向群组 {group_id} 发送《{subject_name}》更新通知失败: {e}"
                )
