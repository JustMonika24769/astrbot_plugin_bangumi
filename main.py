# main.py
import aiohttp
import asyncio
import os
import re
import json
import time
from urllib.parse import quote
from typing import Dict, Any, List, Optional, Tuple

from astrbot.api.message_components import Node, Plain, Image as AstrImage
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.all import AstrBotConfig
from astrbot.api import logger

# 从 method.py 导入工具函数和常量
from .method import get_img_changeFormat, TEMP_DIR

# --- 自定义异常 ---
class NoSubjectFound(Exception):
    """找不到对应条目的异常类"""
    pass

class BangumiApiError(Exception):
    """Bangumi API请求错误的异常类"""
    pass

class BangumiRateLimitError(Exception):
    """API限流异常类"""
    pass

# --- API交互类 ---
class API_Bangumi():
    def __init__(self, access_token: str, user_agent: str):
        if not access_token:
            raise ValueError("Bangumi access_token 未设置, 插件无法工作。")
        self.base_url = "https://api.bgm.tv"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": user_agent
        }
        # 类型映射
        self.type_map = {
            1: "📚 书籍",
            2: "🎬 动画",
            3: "🎵 音乐",
            4: "🎮 游戏",
            6: "🌐 三次元"
        }
        self.character_type_map = {
            1: "👤 角色",
            2: "🤖 机体",
            3: "🚢 舰船",
            4: "🏢 组织"
        }
        self.person_type_map = {
            1: "👤 个人",
            2: "🏢 公司",
            3: "👥 组合"
        }
        self.search_cache: Dict[str, Dict] = {}
        self.last_request_time = 0

    async def _request(self, url: str, method: str = 'GET', params: Dict[str, Any] = None,
                      json_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """通用API请求函数，带限流处理"""
        current_time = time.time()
        if current_time - self.last_request_time < 1.1:
            await asyncio.sleep(1.1 - (current_time - self.last_request_time))
        self.last_request_time = time.time()

        logger.info(f"Bangumi API请求: {method} {url}")
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                if method.upper() == 'POST':
                    async with session.post(url, json=json_data, params=params) as response:
                        return await self._handle_response(response)
                else:
                    async with session.get(url, params=params) as response:
                        return await self._handle_response(response)
        except aiohttp.ClientError as e:
            logger.error(f"网络请求失败: {e}")
            raise BangumiApiError("网络连接异常，请稍后再试")

    async def _handle_response(self, response: aiohttp.ClientResponse) -> Dict:
        """处理API响应"""
        if response.status == 200:
            return await response.json()
        elif response.status == 404:
            raise NoSubjectFound("未找到相关条目")
        elif response.status == 429:
            raise BangumiRateLimitError("API请求过于频繁，请稍后再试")
        else:
            # 尝试解析JSON错误，如果失败再返回文本
            try:
                error_data = await response.json()
                error_text = json.dumps(error_data, ensure_ascii=False)
            except (json.JSONDecodeError, aiohttp.ContentTypeError):
                error_text = await response.text()
            logger.error(f"API错误: {response.status} - {error_text}")
            raise BangumiApiError(f"API服务异常 ({response.status})")

    # --- 条目相关方法 ---
    async def search_subjects(self, keyword: str, limit: int = 10) -> Dict[str, Any]:
        """通过关键词搜索条目"""
        cache_key = f"search:{keyword}:{limit}"
        if cache_key in self.search_cache:
            return self.search_cache[cache_key]

        url = f"{self.base_url}/v0/search/subjects"
        json_data = {'keyword': keyword}
        params = {'limit': limit}

        data = await self._request(url, method='POST', json_data=json_data, params=params)

        self.search_cache[cache_key] = data
        asyncio.get_event_loop().call_later(300, lambda: self.search_cache.pop(cache_key, None))

        return data

    async def get_subject_details(self, subject_id: int) -> Dict[str, Any]:
        """获取单个条目的详细信息"""
        url = f"{self.base_url}/v0/subjects/{subject_id}"
        return await self._request(url)

    def format_subject_info(self, subject: Dict[str, Any]) -> str:
        """格式化条目信息为Markdown"""
        name = subject.get('name', '未知名称')
        name_cn = subject.get('name_cn', name) or name

        type_id = subject.get('type', 2)
        type_str = self.type_map.get(type_id, self.type_map[2])
        date_str = subject.get('date', '未知日期')

        rating = subject.get('rating', {})
        score = rating.get('score', 0)
        total_votes = rating.get('total', 0)
        rank = subject.get('rank', 0)

        summary = subject.get('summary', '暂无简介')
        summary = re.sub(r'<br\s*/?>', '\n', summary)
        summary = re.sub(r'<.*?>', '', summary)

        tags = ", ".join([tag['name'] for tag in subject.get('tags', [])[:5]])

        info_str = (
            f"**{name_cn}**\n"
            f"原名: {name}\n"
            f"类型: {type_str} | 日期: {date_str}\n"
            f"评分: ⭐ {score} (基于{total_votes}人评分)"
            f"{' | 排名: #' + str(rank) if rank else ''}\n"
            f"标签: {tags or '无'}\n"
            f"ID: `{subject.get('id')}`\n"
            f"---\n"
            f"{summary}"
        )
        return info_str

    def format_fuzzy_list(self, data: Dict[str, Any], limit: int) -> str:
        """格式化模糊搜索结果"""
        results = data.get('data', [])
        if not results:
            return "🔍 未找到相关条目"

        output = ["找到以下条目：\n"]
        for i, item in enumerate(results[:limit], 1):
            name_cn = item.get('name_cn') or item.get('name', '未知名称')
            item_type = self.type_map.get(item.get('type'), '🎬 动画')
            date = item.get('date', '未知日期')
            output.append(f"{i}. {name_cn} ({item_type}, {date}) ID: `{item['id']}`")

        if data.get('total', 0) > limit:
            output.append(f"\n共找到 {data['total']} 个结果, 显示前 {limit} 个")

        return "\n".join(output)

    async def search_characters(self, keyword: str, limit: int = 10) -> Dict[str, Any]:
        """通过关键词搜索角色"""
        url = f"{self.base_url}/v0/search/characters"
        json_data = {'keyword': keyword}
        params = {'limit': limit}
        return await self._request(url, method='POST', json_data=json_data, params=params)

    async def get_character_details(self, character_id: int) -> Dict[str, Any]:
        """获取单个角色的详细信息"""
        url = f"{self.base_url}/v0/characters/{character_id}"
        return await self._request(url)

    def format_character_info(self, character: Dict[str, Any]) -> str:
        """格式化角色信息为Markdown"""
        name = character.get('name', '未知名称')

        type_id = character.get('type', 1)
        type_str = self.character_type_map.get(type_id, self.character_type_map[1])

        gender = character.get('gender', '未知')
        summary = character.get('summary', '暂无简介')
        summary = re.sub(r'<br\s*/?>', '\n', summary)
        summary = re.sub(r'<.*?>', '', summary)

        info_str = (
            f"**{name}**\n"
            f"类型: {type_str} | 性别: {gender}\n"
            f"ID: `{character.get('id')}`\n"
            f"---\n"
            f"{summary}"
        )
        return info_str

    def format_character_list(self, data: Dict[str, Any], limit: int) -> str:
        """格式化角色搜索结果"""
        results = data.get('data', [])
        if not results:
            return "🔍 未找到相关角色"

        output = ["找到以下角色：\n"]
        for i, item in enumerate(results[:limit], 1):
            item_name = item.get('name', '未知名称')
            item_type = self.character_type_map.get(item.get('type'), '👤 角色')
            output.append(f"{i}. {item_name} ({item_type}) ID: `{item['id']}`")

        if data.get('total', 0) > limit:
            output.append(f"\n共找到 {data['total']} 个结果, 显示前 {limit} 个")

        return "\n".join(output)

    # --- 新增人物相关方法 ---
    async def search_persons(self, keyword: str, limit: int = 10) -> Dict[str, Any]:
        """通过关键词搜索人物"""
        url = f"{self.base_url}/v0/search/persons"
        json_data = {'keyword': keyword}
        params = {'limit': limit}
        return await self._request(url, method='POST', json_data=json_data, params=params)

    async def get_person_details(self, person_id: int) -> Dict[str, Any]:
        """获取单个人物的详细信息"""
        url = f"{self.base_url}/v0/persons/{person_id}"
        return await self._request(url)

    def format_person_info(self, person: Dict[str, Any]) -> str:
        """格式化人物信息为Markdown"""
        name = person.get('name', '未知名称')

        type_id = person.get('type', 1)
        type_str = self.person_type_map.get(type_id, self.person_type_map[1])

        career = ", ".join(person.get('career', [])) or "未知"
        summary = person.get('summary', '暂无简介')
        summary = re.sub(r'<br\s*/?>', '\n', summary)
        summary = re.sub(r'<.*?>', '', summary)

        info_str = (
            f"**{name}**\n"
            f"类型: {type_str} | 职业: {career}\n"
            f"ID: `{person.get('id')}`\n"
            f"---\n"
            f"{summary}"
        )
        return info_str

    def format_person_list(self, data: Dict[str, Any], limit: int) -> str:
        """格式化人物搜索结果"""
        results = data.get('data', [])
        if not results:
            return "🔍 未找到相关人物"

        output = ["找到以下人物：\n"]
        for i, item in enumerate(results[:limit], 1):
            item_name = item.get('name', '未知名称')
            item_type = self.person_type_map.get(item.get('type'), '👤 个人')
            output.append(f"{i}. {item_name} ({item_type}) ID: `{item['id']}`")

        if data.get('total', 0) > limit:
            output.append(f"\n共找到 {data['total']} 个结果, 显示前 {limit} 个")

        return "\n".join(output)

    # --- 新增用户相关方法 ---
    async def get_user_details(self, username: str) -> Dict[str, Any]:
        """获取用户详细信息"""
        encoded_username = quote(username)
        url = f"{self.base_url}/v0/users/{encoded_username}"
        return await self._request(url)

    def format_user_info(self, user: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        """格式化用户信息并返回头像URL"""
        username = user.get('username', '未知用户名')
        nickname = user.get('nickname', username)
        sign = user.get('sign', '暂无签名')
        sign = re.sub(r'<.*?>', '', sign)  # 移除HTML标签

        # 用户组映射
        group_map = {
            1: "管理员", 2: "Bangumi 管理猿", 3: "天窗管理猿",
            4: "禁言用户", 5: "禁止访问用户", 8: "人物管理猿",
            9: "维基条目管理猿", 10: "用户", 11: "维基人"
        }
        group_id = user.get('user_group', 10)
        group_str = group_map.get(group_id, "用户")

        # 获取头像URL
        avatar_url = user.get('avatar', {}).get('large')

        info_str = (
            f"**{nickname} (@{username})**\n"
            f"用户组: {group_str}\n"
            f"签名: {sign}\n"
            f"ID: `{user.get('id')}`"
        )
        return info_str, avatar_url


# --- Astrbot 插件主类 ---
@register(
    "astrbot_plugin_bangumi",
    "Gemini",
    "一个用于查询Bangumi条目信息的插件",
    "1.2.0",  # 版本号更新
    "https://github.com/bangumi/api"
)
class BangumiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.access_token = self.config.get("access_token", "")
        self.user_agent = self.config.get("user_agent", "AstrBot-Bangumi-Plugin/2.0")
        self.max_fuzzy_results = int(self.config.get("max_fuzzy_results", 5))
        self.use_forward_msg = self.config.get("use_forward", "关闭") == "开启"
        self.use_filesystem = self.config.get("if_fromfilesystem", "关闭") == "开启"

        try:
            self.bgm_api = API_Bangumi(self.access_token, self.user_agent)
            logger.info("Bangumi插件初始化成功")
        except ValueError as e:
            logger.error(f"插件初始化失败: {e}")
            self.bgm_api = None

    # --- 命令处理 ---
    @filter.command("bgm搜索")
    async def accurate_search(self, event: AstrMessageEvent):
        """准确搜索条目 - 用法: /bgm搜索 <关键词|ID>"""
        if not self.bgm_api:
            return event.plain_result("❌ Bangumi插件未正确配置")

        cmd = event.message_str.split(maxsplit=1)
        if len(cmd) < 2:
            return event.plain_result("❌ 格式错误，用法: /bgm搜索 <关键词|ID>")

        query = cmd[1].strip()

        try:
            event.plain_result(f"🔍 正在搜索: {query} ...")

            if query.isdigit():
                # ID搜索
                subject = await self.bgm_api.get_subject_details(int(query))
            else:
                # 关键词搜索
                search_data = await self.bgm_api.search_subjects(query, limit=1)
                if not search_data.get('data'):
                    return event.plain_result(f"❌ 未找到相关条目: {query}")
                subject_id = search_data['data'][0]['id']
                subject = await self.bgm_api.get_subject_details(subject_id)

            info_text = self.bgm_api.format_subject_info(subject)
            img_url = subject.get('images', {}).get('large')

            return await self._build_reply(img_url, info_text, event)

        except NoSubjectFound:
            return event.plain_result(f"❌ 未找到相关条目: {query}")
        except BangumiRateLimitError:
            return event.plain_result("⚠️ 请求过于频繁，请稍后再试")
        except BangumiApiError as e:
            return event.plain_result(f"❌ API错误: {str(e)}")
        except Exception as e:
            logger.exception("准确搜索异常")
            return event.plain_result("❌ 内部错误，请查看日志")

    @filter.command("bgm模糊")
    async def fuzzy_search(self, event: AstrMessageEvent):
        """模糊搜索条目 - 用法: /bgm模糊 <关键词>"""
        if not self.bgm_api:
            return event.plain_result("❌ Bangumi插件未正确配置")
        
        cmd = event.message_str.split(maxsplit=1)
        if len(cmd) < 2:
            return event.plain_result("❌ 格式错误，用法: /bgm模糊 <关键词>")
        
        query = cmd[1].strip()
        
        try:
            event.plain_result(f"🔍 正在模糊搜索: {query} ...")
            search_data = await self.bgm_api.search_subjects(query, limit=self.max_fuzzy_results)
            result_text = self.bgm_api.format_fuzzy_list(search_data, self.max_fuzzy_results)
            
            if self.use_forward_msg:
                node = Node(uin=event.bot.self_id, name="Bangumi模糊搜索", content=[Plain(result_text)])
                return event.chain_result([node])
            return event.plain_result(result_text)
            
        except BangumiRateLimitError:
            return event.plain_result("⚠️ 请求过于频繁，请稍后再试")
        except BangumiApiError as e:
            return event.plain_result(f"❌ API错误: {str(e)}")
        except Exception as e:
            logger.exception("模糊搜索异常")
            return event.plain_result("❌ 内部错误，请查看日志")

    @filter.command("bgm角色")
    async def get_character(self, event: AstrMessageEvent):
        """获取角色详情 - 用法: /bgm角色 <角色ID|关键词>"""
        if not self.bgm_api:
            return event.plain_result("❌ Bangumi插件未正确配置")

        cmd = event.message_str.split(maxsplit=1)
        if len(cmd) < 2:
            return event.plain_result("❌ 格式错误，用法: /bgm角色 <角色ID|关键词>")

        query = cmd[1].strip()

        try:
            event.plain_result(f"🔍 正在查询角色: {query} ...")
            if query.isdigit():
                character = await self.bgm_api.get_character_details(int(query))
            else:
                search_data = await self.bgm_api.search_characters(query, limit=1)
                if not search_data.get('data'):
                    return event.plain_result(f"❌ 未找到相关角色: {query}")
                character_id = search_data['data'][0]['id']
                character = await self.bgm_api.get_character_details(character_id)

            info_text = self.bgm_api.format_character_info(character)
            img_url = character.get('images', {}).get('large')

            return await self._build_reply(img_url, info_text, event)

        except NoSubjectFound:
            return event.plain_result(f"❌ 未找到相关角色: {query}")
        except BangumiRateLimitError:
            return event.plain_result("⚠️ 请求过于频繁，请稍后再试")
        except BangumiApiError as e:
            return event.plain_result(f"❌ API错误: {str(e)}")
        except Exception as e:
            logger.exception("角色查询异常")
            return event.plain_result("❌ 内部错误，请查看日志")

    @filter.command("bgm角色搜索")
    async def fuzzy_search_characters(self, event: AstrMessageEvent):
        """模糊搜索角色 - 用法: /bgm角色搜索 <关键词>"""
        if not self.bgm_api:
            return event.plain_result("❌ Bangumi插件未正确配置")
        
        cmd = event.message_str.split(maxsplit=1)
        if len(cmd) < 2:
            return event.plain_result("❌ 格式错误，用法: /bgm角色搜索 <关键词>")
        
        query = cmd[1].strip()
        
        try:
            event.plain_result(f"🔍 正在搜索角色: {query} ...")
            search_data = await self.bgm_api.search_characters(query, limit=self.max_fuzzy_results)
            result_text = self.bgm_api.format_character_list(search_data, self.max_fuzzy_results)
            
            if self.use_forward_msg:
                node = Node(uin=event.bot.self_id, name="Bangumi角色搜索", content=[Plain(result_text)])
                return event.chain_result([node])
            return event.plain_result(result_text)
            
        except BangumiRateLimitError:
            return event.plain_result("⚠️ 请求过于频繁，请稍后再试")
        except BangumiApiError as e:
            return event.plain_result(f"❌ API错误: {str(e)}")
        except Exception as e:
            logger.exception("角色搜索异常")
            return event.plain_result("❌ 内部错误，请查看日志")

    @filter.command("bgm人物")
    async def get_person(self, event: AstrMessageEvent):
        """获取人物详情 - 用法: /bgm人物 <人物ID|关键词>"""
        if not self.bgm_api:
            return event.plain_result("❌ Bangumi插件未正确配置")
        
        cmd = event.message_str.split(maxsplit=1)
        if len(cmd) < 2:
            return event.plain_result("❌ 格式错误，用法: /bgm人物 <人物ID|关键词>")
        
        query = cmd[1].strip()
        
        try:
            event.plain_result(f"🔍 正在查询人物: {query} ...")
            if query.isdigit():
                person = await self.bgm_api.get_person_details(int(query))
            else:
                search_data = await self.bgm_api.search_persons(query, limit=1)
                if not search_data.get('data'):
                    return event.plain_result(f"❌ 未找到相关人物: {query}")
                person_id = search_data['data'][0]['id']
                person = await self.bgm_api.get_person_details(person_id)

            info_text = self.bgm_api.format_person_info(person)
            img_url = person.get('images', {}).get('large')
            
            return await self._build_reply(img_url, info_text, event)
            
        except NoSubjectFound:
            return event.plain_result(f"❌ 未找到相关人物: {query}")
        except BangumiRateLimitError:
            return event.plain_result("⚠️ 请求过于频繁，请稍后再试")
        except BangumiApiError as e:
            return event.plain_result(f"❌ API错误: {str(e)}")
        except Exception as e:
            logger.exception("人物查询异常")
            return event.plain_result("❌ 内部错误，请查看日志")

    @filter.command("bgm人物搜索")
    async def fuzzy_search_persons(self, event: AstrMessageEvent):
        """模糊搜索人物 - 用法: /bgm人物搜索 <关键词>"""
        if not self.bgm_api:
            return event.plain_result("❌ Bangumi插件未正确配置")
        
        cmd = event.message_str.split(maxsplit=1)
        if len(cmd) < 2:
            return event.plain_result("❌ 格式错误，用法: /bgm人物搜索 <关键词>")
        
        query = cmd[1].strip()
        
        try:
            event.plain_result(f"🔍 正在搜索人物: {query} ...")
            search_data = await self.bgm_api.search_persons(query, limit=self.max_fuzzy_results)
            result_text = self.bgm_api.format_person_list(search_data, self.max_fuzzy_results)
            
            if self.use_forward_msg:
                node = Node(uin=event.bot.self_id, name="Bangumi人物搜索", content=[Plain(result_text)])
                return event.chain_result([node])
            return event.plain_result(result_text)
            
        except BangumiRateLimitError:
            return event.plain_result("⚠️ 请求过于频繁，请稍后再试")
        except BangumiApiError as e:
            return event.plain_result(f"❌ API错误: {str(e)}")
        except Exception as e:
            logger.exception("人物搜索异常")
            return event.plain_result("❌ 内部错误，请查看日志")

    @filter.command("bgm用户")
    async def get_user(self, event: AstrMessageEvent):
        """获取用户信息 - 用法: /bgm用户 <用户名>"""
        if not self.bgm_api:
            return event.plain_result("❌ Bangumi插件未正确配置")
        
        cmd = event.message_str.split(maxsplit=1)
        if len(cmd) < 2:
            return event.plain_result("❌ 格式错误，用法: /bgm用户 <用户名>")
        
        username = cmd[1].strip()
        
        try:
            event.plain_result(f"🔍 正在查询用户: {username} ...")
            user = await self.bgm_api.get_user_details(username)
            info_text, avatar_url = self.bgm_api.format_user_info(user)
            
            return await self._build_reply(avatar_url, info_text, event)
            
        except NoSubjectFound:
            return event.plain_result(f"❌ 未找到相关用户: {username}")
        except BangumiRateLimitError:
            return event.plain_result("⚠️ 请求过于频繁，请稍后再试")
        except BangumiApiError as e:
            return event.plain_result(f"❌ API错误: {str(e)}")
        except Exception as e:
            logger.exception("用户查询异常")
            return event.plain_result("❌ 内部错误，请查看日志")

    async def send(self, event: AstrMessageEvent, content: List[Any]):
        """发送消息"""
        pass

    # --- 通用构建回复方法 ---
    async def _build_reply(self, img_url: Optional[str], info_text: str, event: AstrMessageEvent):
        """构建并发送带有图片和文本的回复"""
        message_content = []
        temp_file_path = None
        
        try:
            if img_url:
                try:
                    # 【已修复】调用导入的函数，不再传递 ssl=False
                    img_path = await get_img_changeFormat(img_url, TEMP_DIR)
                    temp_file_path = img_path
                    
                    if self.use_filesystem:
                        message_content.append(AstrImage.fromFileSystem(img_path))
                    else:
                        with open(img_path, "rb") as f:
                            message_content.append(AstrImage.fromBytes(f.read()))
                except Exception as e:
                    logger.warning(f"图片处理失败，将仅发送文本: {e}")
            
            message_content.append(Plain(info_text))
            
            # 发送消息
            return event.chain_result(message_content)
        
        finally:
            # 确保临时文件在函数结束时被清理
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    await asyncio.sleep(1) # 稍作等待，确保文件已发送
                    os.remove(temp_file_path)
                except Exception as e:
                    logger.warning(f"临时文件清理失败: {e}")

    async def terminate(self):
        """插件卸载"""
        logger.info("Bangumi插件已卸载")
