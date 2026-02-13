import asyncio
import os
import sys
import tempfile
import datetime
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.all import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register, StarTools

# 导入配置管理器
from .src.config.config_manager import ConfigManager
from .src.render.calendar_renderer import CalendarRenderer
from .src.render.subject_renderer import SubjectRenderer
from .src.utils.scheduler import SchedulerManager

# 导入我们重构后的统一API类
from .src.services import BangumiService
from .src.db import BangumiRepository


@register(
    "astrbot_plugin_bangumi",
    "Gemini",
    "一个用于查询Bangumi条目信息的插件",
    "1.3.0",
    "https://github.com/united-pooh/astrbot_plugin_bangumi",
)
class BangumiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        """
        初始化 BangumiPlugin 插件。
        负责设置插件的上下文、配置、配置管理器、调度管理器、最大模糊搜索结果数，
        并初始化存储和 Bangumi API 服务。

        :param context: 插件的上下文对象，用于访问 AstrBot 核心功能。
        :param config: AstrBot 的配置对象，包含插件所需的各种配置。
        """
        super().__init__(context)
        self.config = config
        self.config_manager = ConfigManager(config)
        self.scheduler_manager = SchedulerManager()
        self.max_fuzzy_results = 10

        # 1. 优先初始化存储，确保即使网络配置失败也能访问数据库
        try:
            self.storage = BangumiRepository()
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            self.storage = None

        self.service = None
        try:
            # 构造代理 URL
            proxy_url = None
            proxy_host = self.config_manager.get_proxy_http()
            proxy_port = self.config_manager.get_port()
            if proxy_host and proxy_port:
                proxy_url = f"{proxy_host}:{proxy_port}"

            # 初始化 API 服务
            self.service = BangumiService(
                access_token=self.config_manager.get_access_token(),
                user_agent=self.config_manager.get_user_agent(),
                proxy=proxy_url,
            )

        except ValueError as e:
            logger.error(f"插件配置错误: {e}")
        except Exception as e:
            logger.error(f"服务初始化失败: {e}")

    async def _verify_playwright(self) -> bool:
        """
        验证 Playwright 是否安装成功并可运行。
        """
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                )
                await browser.close()
            return True
        except Exception as e:
            logger.debug(f"Playwright 验证运行失败: {e}")
            return False

    async def initialize(self):
        """
        插件加载时自动运行的初始化方法。
        检查并安装必要的依赖（如 Playwright 及其 Chromium 浏览器），并在需要时重新运行安装。
        同时，会添加定时任务用于更新番剧信息。

        :return: None
        """
        # 获取插件数据目录
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        data_dir = get_astrbot_data_path()
        flag_file = os.path.join(
            data_dir, "plugin_data", "astrbot_plugin_bangumi", ".playwright_installed"
        )

        need_install = False
        if os.path.exists(flag_file):
            logger.info("Playwright 依赖标记已存在，正在验证环境...")
            if not await self._verify_playwright():
                logger.warning("Playwright 环境验证失败，将尝试重新安装。")
                need_install = True
            else:
                logger.info("Playwright 验证通过。")
        else:
            need_install = True

        if need_install:
            logger.info("正在初始化插件依赖 (Playwright)...")
            try:
                # 安装 Playwright 系统依赖
                logger.info("正在运行 playwright install-deps...")
                process = await asyncio.create_subprocess_shell(
                    f"{sys.executable} -m playwright install-deps",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await process.communicate()
                if process.returncode != 0:
                    logger.warning(f"系统依赖安装返回非零状态 (可能非关键): {stderr.decode()}")

                # 安装 Playwright Chromium
                logger.info("正在安装 Playwright Chromium...")
                process = await asyncio.create_subprocess_shell(
                    f"{sys.executable} -m playwright install chromium",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await process.communicate()

                if process.returncode == 0:
                    # 再次验证
                    if await self._verify_playwright():
                        logger.info("Playwright Chromium 安装并验证成功")
                        # 创建/更新标记文件
                        os.makedirs(os.path.dirname(flag_file), exist_ok=True)
                        with open(flag_file, "w") as f:
                            f.write("installed")
                    else:
                        logger.error("Playwright 安装后验证依然失败，请检查网络或手动安装依赖。")
                else:
                    logger.warning(f"Playwright Chromium 安装返回错误: {stderr.decode()}")

            except Exception as e:
                logger.error(f"依赖安装流程失败: {e}")

        # 始终尝试添加定时任务，即便渲染环境有问题，API 查询仍可工作
        try:
            self.scheduler_manager.add_job(
                func=self.update_episodes, trigger="cron", minute=0
            )
            logger.info("Bangumi 插件定时任务已启动")
        except Exception as e:
            logger.error(f"添加定时任务失败: {e}")

        logger.info("Bangumi 插件初始化流程结束")

    async def notify_subscribers(
        self,
        subject_id: str,
        subject_name: str,
        new_episode_number: int,
    ):
        """
        向订阅了指定番剧的所有群组发送更新通知。
        """
        subscribed_groups = self.storage.get_subject_subscribers(subject_id)
        message = f"《{subject_name}》更新啦！当前最新集数：{new_episode_number}"
        from astrbot.core.message.message_event_result import MessageChain

        chain = MessageChain()
        for group_id in subscribed_groups:
            try:
                # 类方法直接通过类调用，cls 会自动传入
                await StarTools.send_message_by_id(
                    type="GroupMessage",
                    id=group_id,
                    message_chain=chain.message(message),
                )
                logger.info(f"向群组 {group_id} 发送《{subject_name}》更新通知成功。")
            except Exception as e:
                logger.error(
                    f"向群组 {group_id} 发送《{subject_name}》更新通知失败: {e}"
                )

    async def update_episodes(self):
        """
        定时任务：更新所有已订阅番剧的最新集数。

        流程：
        1. 从数据库获取所有被订阅的番剧
        2. 逐个调用 API 获取最新 episode
        3. 比对数据库中的 current_episode，如果有更新则更新数据库并通知
        """
        # 1. 获取所有被订阅的番剧
        subjects = self.storage.get_monitored_subjects()
        logger.info(f"开始更新 {len(subjects)} 个番剧的集数信息")

        for subject in subjects:
            try:
                # 2. 获取最新 episode
                latest_episode = await self.service.get_latest_episode(
                    int(subject.subject_id)
                )
                if not latest_episode:
                    continue

                # 3. 比对并更新
                if latest_episode.ep > subject.current_episode:
                    logger.info(
                        f"番剧《{subject.name}》有更新: {subject.current_episode} -> {latest_episode.ep}"
                    )
                    self.storage.update_subject_episode(
                        subject.subject_id, latest_episode.ep
                    )
                    await self.notify_subscribers(
                        subject.subject_id, subject.name, latest_episode.ep
                    )
            except Exception as e:
                logger.error(f"更新番剧《{subject.name}》失败: {e}")

    # --- 内部核心逻辑 ---

    async def _render_subjects(
        self, subjects: list, top_k: int = 1
    ) -> tuple[list[Comp.Image], list[str], list[str]]:
        """
        核心渲染逻辑：处理条目列表，获取详情并生成图片。
        从给定的条目列表中获取指定数量的条目详情，然后使用 `SubjectRenderer`
        将这些条目渲染成图片，并返回图片组件、临时文件路径和成功的条目ID列表。

        :param subjects: 条目列表，可以是包含 'id' 的字典列表，也可以是 ID 列表。
                         例如：`[{'id': 123, 'name': 'Anime Name'}, ...]` 或 `[123, 456]`。
        :param top_k: 最大处理数量。表示从 `subjects` 列表中最多处理的条目数量。
                      默认为 1。

        :return: 一个包含三个元素的元组：
                 - `list[Comp.Image]`: 生成的图片组件列表，每个组件代表一个渲染的条目图片。
                 - `list[str]`: 产生的临时文件路径列表，这些文件包含了渲染的图片。
                                调用者负责在图片发送后清理这些临时文件。
                 - `list[str]`: 成功获取并渲染的条目 ID 列表。
        """
        subjects_id_list = []
        data_list = []
        temp_files = []
        # 构造第一个传入参数
        for item in subjects[:top_k]:
            subject_id = None
            if isinstance(item, dict):
                subject_id = item.get("id", None)
            if subject_id is None:
                continue
            subjects_id_list.append(subject_id)

            subject_data = await self.service.get_subject_details(subject_id)
            if len(subject_data) == 0:
                logger.warning(f"获取条目 {subject_id} 详情失败，跳过")
                continue

            # 获取剧集信息用于渲染 episode 进度
            try:
                episodes_data = await self.service.get_subject_episodes(subject_id)
                if episodes_data and "data" in episodes_data:
                    subject_data["episodes"] = episodes_data["data"]
            except Exception as e:
                logger.warning(f"获取条目 {subject_id} 剧集信息失败: {e}")

            data_list.append(subject_data)

            # 创建临时文件
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
            os.close(tmp_fd)  # 立即关闭文件描述符，只保留路径
            temp_files.append(tmp_path)

        # 创建渲染器实例
        renderer = SubjectRenderer()
        await renderer.render_batch_subject_cards(
            data_list=data_list, output_paths=temp_files
        )
        image_components = []
        try:
            for path in temp_files:
                if os.path.exists(path) and os.path.getsize(path) > 0:
                    image_components.append(Comp.Image.fromFileSystem(path))
                else:
                    logger.warning("图片生成失败")
        except Exception as e:
            logger.error(f"渲染图片失败: {e}")

        return image_components, temp_files, subjects_id_list

    async def _handle_subject(
        self,
        event: AstrMessageEvent,
        query: str,
        top_k: int | None = None,
        subject_type: list[int] | None = None,
        subject_tags: list[str] | None = None,
    ):
        """
        通用搜索处理逻辑：搜索 -> 渲染 -> 发送 -> 清理。
        根据查询字符串和可选的类型、标签搜索 Bangumi 条目，然后渲染成图片并发送。
        处理过程中会生成临时图片文件，并在发送后进行清理。

        :param event: 消息平台事件对象，用于发送回复。
        :param query: 查询字符串或条目 ID。
        :param top_k: 与查询内容最接近的 `k` 个搜索结果。默认为 1。
        :param subject_type: 查询内容的类型列表，例如 [1] 表示书籍，[2] 表示动画等。
        :param subject_tags: 查询内容的标签列表，例如 ["TV"]。

        :return: 异步迭代器，每次产出一个 AstrMessageEvent.plain_result 或 AstrMessageEvent.chain_result 对象，
                用于向用户发送文本消息或图片消息。
        """
        if not self.service:
            yield event.plain_result("❌ 配置未完成")
            return

        if not query:
            yield event.plain_result("❌ 请提供搜索关键词")
            return

        # 处理 top_k
        if top_k is None:
            top_k = 1
        try:
            top_k = int(top_k)
        except (ValueError, TypeError):
            top_k = 1

        logger.info(f"搜索: {query}, type={subject_type}, top_k={top_k}")

        try:
            # 1. 搜索条目
            search_res = await self.service.search_subjects(
                keyword=query, subject_type=subject_type, subject_tags=subject_tags
            )
            if not search_res or "data" not in search_res or not search_res["data"]:
                yield event.plain_result("🔍 未找到相关条目")
                return

            # 2. 渲染条目
            (
                image_components,
                temp_files,
                subjects_id_list,
            ) = await self._render_subjects(search_res["data"], top_k)

            # 3. 发送图片
            if image_components:
                yield event.chain_result(image_components)
            else:
                yield event.plain_result("❌ 未能生成任何图片")

            # 4. 清理临时文件
            await asyncio.sleep(1)
            for path in temp_files:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception as e:
                    logger.warning(f"清理临时文件失败 {path}: {e}")

        except Exception as e:
            logger.error(f"处理搜索请求失败: {e}")
            yield event.plain_result(f"❌ 处理失败: {e}")

    async def _handle_calendar(
        self, event: AstrMessageEvent, api_result: list[dict[str, Any]] | None = None
    ):
        """
        处理 Bangumi 每日放送的渲染和发送逻辑。
        获取每日放送数据，渲染成日历图片，然后发送给用户，并清理临时文件。

        :param event: 消息平台事件对象，用于发送回复。
        :param api_result: (可选) 预先获取的 API 结果，如果提供则跳过 API 调用。

        :return: 异步迭代器，每次产出一个 AstrMessageEvent.plain_result 或 AstrMessageEvent.chain_result 对象，
                用于向用户发送文本消息或图片消息。
        """
        if not self.service:
            yield event.plain_result("❌ 配置未完成")
            return

        try:
            # 1. 获取每日放送
            calendar_res = await self.service.get_calendar()

            if not calendar_res:
                yield event.plain_result("❌ 未获取到放送数据")
                return

            # 2. 渲染图片
            renderer = CalendarRenderer()

            # 创建临时文件
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
            os.close(tmp_fd)

            try:
                await renderer.render_calendar(
                    calendar_res,
                    output_path=tmp_path,
                    max_retries=self.config_manager.get_max_retries(),
                )

                # 3. 发送图片
                if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                    yield event.chain_result([Comp.Image.fromFileSystem(tmp_path)])
                else:
                    yield event.plain_result("❌ 图片生成失败")

                # 4. 清理临时文件
                await asyncio.sleep(1)
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

            except Exception as e:
                logger.error(f"渲染放送表失败: {e}")
                yield event.plain_result(f"❌ 渲染失败: {e}")
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except:
                        pass

        except Exception as e:
            logger.error(f"处理每日放送失败: {e}")
            yield event.plain_result(f"❌ 处理失败: {e}")

    # --- 命令处理区 ---

    @filter.command("bgm搜索")
    async def search(
        self, event: AstrMessageEvent, query: str, top_k: int | None = None
    ):
        """
        通用搜索命令。
        通过 `_handle_subject` 方法处理用户的通用搜索请求，
        可以搜索任何类型的 Bangumi 条目（动画、书籍、音乐、游戏、三次元）。

        :param event: 消息平台事件对象。
        :param query: 用户的搜索关键词。
        :param top_k: (可选) 与查询内容最接近的 `k` 个搜索结果。默认为 1。

        :return: 异步迭代器，产出搜索结果。
        """
        async for result in self._handle_subject(
            event, query, top_k, subject_type=None
        ):
            yield result

    @filter.command("bgm番剧")
    async def search_anime(
        self, event: AstrMessageEvent, query: str, top_k: int | None = None
    ):
        """
        搜索番剧命令。
        通过 `_handle_subject` 方法处理用户的番剧搜索请求，
        限定搜索类型为动画 (subject_type=[2]) 且标签包含 "TV"。

        :param event: 消息平台事件对象。
        :param query: 用户的番剧搜索关键词。
        :param top_k: (可选) 与查询内容最接近的 `k` 个搜索结果。默认为 1。

        :return: 异步迭代器，产出番剧搜索结果。
        """
        async for result in self._handle_subject(
            event, query, top_k, subject_type=[2], subject_tags=["TV"]
        ):
            yield result

    @filter.command("bgm剧场版")
    async def search_movie(
        self, event: AstrMessageEvent, query: str, top_k: int | None = None
    ):
        """
        搜索剧场版命令。
        通过 `_handle_subject` 方法处理用户的剧场版搜索请求，
        限定搜索类型为动画 (subject_type=[2]) 且标签包含 "剧场版"。

        :param event: 消息平台事件对象。
        :param query: 用户的剧场版搜索关键词。
        :param top_k: (可选) 与查询内容最接近的 `k` 个搜索结果。默认为 1。

        :return: 异步迭代器，产出剧场版搜索结果。
        """
        async for result in self._handle_subject(
            event, query, top_k, subject_type=[2], subject_tags=["剧场版"]
        ):
            yield result

    @filter.command("bgm漫画")
    async def search_manga(
        self, event: AstrMessageEvent, query: str, top_k: int | None = None
    ):
        """
        搜索漫画命令。
        通过 `_handle_subject` 方法处理用户的漫画搜索请求，
        限定搜索类型为书籍 (subject_type=[1]) 且标签包含 "漫画"。

        :param event: 消息平台事件对象。
        :param query: 用户的漫画搜索关键词。
        :param top_k: (可选) 与查询内容最接近的 `k` 个搜索结果。默认为 1。

        :return: 异步迭代器，产出漫画搜索结果。
        """
        async for result in self._handle_subject(
            event, query, top_k, subject_type=[1], subject_tags=["漫画"]
        ):
            yield result

    @filter.command("today")
    async def calendar(self, event: AstrMessageEvent):
        """
        获取今日番剧放送表命令。
        通过 `_handle_calendar` 方法处理用户的请求，获取并发送今日的番剧放送列表。

        Parameter event: 消息平台事件对象。

        Returns: 异步迭代器，产出日历图片或错误消息。
        """
        async for result in self._handle_calendar(event):
            yield result

    @filter.command("bgm_debug")
    async def bgm_debug(self, event: AstrMessageEvent):
        """
        调试指令：查看数据库状态。
        用于检查插件内部存储 (SQLite 数据库) 的路径、文件大小以及其中存储的 BangumiSubject 和 Subscription 数量。
        如果数据库查询失败，也会返回相应的错误信息。

        :param event: 消息平台事件对象。

        :return: 异步迭代器，产出包含数据库状态信息的文本消息。
        """
        if not self.storage:
            yield event.plain_result("Storage not initialized")
            return

        # 测试用：重置番剧 525565 的 current_episode 为 0
        self.storage.update_subject_episode("525565", 0)

        msg = [f"DB Path: {self.storage.db_path}"]
        if os.path.exists(self.storage.db_path):
            msg.append(
                f"File exists, size: {os.path.getsize(self.storage.db_path)} bytes"
            )
        else:
            msg.append("File does NOT exist")

        # 查询数据
        try:
            from .src.db import BangumiSubject, Subscription
            from .src.services.schemas import Episode

            session = self.storage.Session()

            subjects = session.query(BangumiSubject).all()
            msg.append(f"\nSubjects ({len(subjects)}):")
            for s in subjects:
                msg.append(str(s))
                episode: Episode | None = await self.service.get_latest_episode(
                    s.subject_id
                )
                msg.append("最新集数: " + str(episode.ep) if episode else "")

            subs = session.query(Subscription).all()
            msg.append(f"\n订阅详情 ({len(subs)}):")
            for s in subs:
                msg.append(str(s))

            session.close()
        except Exception as e:
            msg.append(f"\nError querying DB: {e}")

        # 设置10秒后更新 episode 的定时任务
        run_time = datetime.datetime.now() + datetime.timedelta(seconds=10)
        job_id = self.scheduler_manager.add_job(
            func=self.update_episodes,
            trigger="date",
            run_date=run_time,
        )
        if job_id:
            msg.append(f"\n⏰ 已设置10秒后更新 episode 的定时任务 (job_id: {job_id})")
        else:
            msg.append("\n❌ 设置定时任务失败")

        yield event.plain_result("\n".join(msg))

    @filter.command("追番")
    async def subscribe(self, event: AstrMessageEvent, query: str):
        """
        订阅番剧命令。
        用户通过提供番剧名称来订阅番剧，插件会将该番剧添加到数据库中，
        并在番剧更新时向发送订阅请求的群组推送消息。

        :param event: 消息平台事件对象，用于获取群组 ID 和发送回复。
        :param query: 用户提供的番剧名称或关键词。

        :return: 异步迭代器，产出订阅成功或失败的文本消息。
        """
        if not self.service:
            yield event.plain_result("❌ 配置未完成")
            return

        # 获取 group_id
        group_id = None
        if hasattr(event, "message_obj") and hasattr(event.message_obj, "group_id"):
            group_id = event.message_obj.group_id
        elif hasattr(event, "session_id"):  # Fallback for some adapters
            group_id = event.session_id

        if not group_id:
            yield event.plain_result("❌ 无法获取群组ID，请在群聊中使用")
            return

        if not query:
            yield event.plain_result("❌ 请提供番剧名称")
            return

        logger.info(f"处理追番请求: {query}, group_id={group_id}")

        try:
            # 使用 Service 层的新方法进行匹配
            error_msg, subject_info = await self.service.match_subscribable_subject(
                query
            )

            if error_msg:
                yield event.plain_result(error_msg)
                return

            if not subject_info:
                yield event.plain_result("❌ 未知错误：未能获取番剧信息")
                return

            # 解包数据
            subject_id = subject_info["subject_id"]
            name = subject_info["name"]

            # 入库
            self.storage.update_subject(
                subject_id=subject_id,
                name=name,
                air_date=subject_info["air_date"],
                total_episodes=subject_info["total_episodes"],
            )

            # 添加订阅
            success = self.storage.add_subscription(group_id, subject_id)

            if success:
                yield event.plain_result(
                    f"✅ 成功订阅《{name}》！\n如有更新将推送到本群。"
                )
            else:
                yield event.plain_result("❌ 订阅失败，数据库错误。")

        except Exception as e:
            logger.error(f"处理追番请求失败: {e}")
            yield event.plain_result(f"❌ 处理失败: {e}")

    def terminate(self):
        """
        插件终止时自动运行的清理方法。
        负责关闭调度器中运行的定时任务，确保插件优雅地停止。

        :return: None
        """
        logger.info("正在清理旧的调度器...")
        if self.scheduler_manager.scheduler.running:
            self.scheduler_manager.scheduler.shutdown(wait=False)  # 强制关闭
