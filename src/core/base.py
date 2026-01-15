import time
import json
import asyncio
import aiohttp
from typing import Dict, Any
from astrbot.api import logger
from .exceptions import BangumiApiError, BangumiRateLimitError, NoSubjectFound


class BaseBangumiService:
    def __init__(self, access_token: str, user_agent: str, proxy: str | None = None):
        if not access_token:
            raise ValueError("Bangumi access_token 未设置")
        self.base_url = "https://api.bgm.tv"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": user_agent,
        }
        self.proxy = proxy
        self.last_request_time = 0
        # 这里只放通用的缓存，或者具体业务的缓存放到具体类中
        self.search_cache: Dict[str, Dict] = {}

    async def _request(
        self,
        url: str,
        method: str = "GET",
        params: Dict[str, Any] | None = None,
        json_data: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        通用API请求函数，带限流处理
        """
        current_time = time.time()
        if current_time - self.last_request_time < 1.1:
            await asyncio.sleep(1.1 - (current_time - self.last_request_time))
        self.last_request_time = time.time()

        logger.info(f"Bangumi API请求: {method} {url}")
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                if method.upper() == "POST":
                    async with session.post(
                        url, json=json_data, params=params, proxy=self.proxy
                    ) as response:
                        return await self._handle_response(response)
                else:
                    async with session.get(url, params=params, proxy=self.proxy) as response:
                        return await self._handle_response(response)
        except aiohttp.ClientError as e:
            logger.error(f"网络请求失败: {e}")
            raise BangumiApiError("网络连接异常，请稍后再试")

    async def _handle_response(self, response: aiohttp.ClientResponse) -> Dict:
        """
        处理api响应
        """
        if response.status == 200:
            return await response.json()
        elif response.status == 404:
            raise NoSubjectFound("未找到相关条目")
        elif response.status == 429:
            raise BangumiRateLimitError("API请求过于频繁")
        else:
            try:
                error_data = await response.json()
                error_text = json.dumps(error_data, ensure_ascii=False)
            except Exception as _:
                error_text = await response.text()
            logger.error(f"API错误: {response.status} - {error_text}")
            raise BangumiApiError(f"API服务异常 ({response.status})")
