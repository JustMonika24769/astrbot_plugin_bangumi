import asyncio
import json
import time
from typing import Any, Dict, Optional

import aiohttp


from astrbot.api import logger

from .exceptions import BangumiApiError, BangumiRateLimitError, NoSubjectFound


class BaseBangumiService:
    def __init__(
        self,
        access_token: str,
        user_agent: str,
        proxy: str | None = None,
        max_retries: int = 3,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        if not access_token:
            raise ValueError("Bangumi access_token 未设置")
        self.base_url = "https://api.bgm.tv"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": user_agent,
        }
        self.proxy = proxy
        self.last_request_time = 0.0
        self._rate_lock = asyncio.Lock()
        self._timeout = aiohttp.ClientTimeout(total=30, connect=10)
        # 兜底 session（惰性创建，避免每次新建 TCP 连接）
        self._fallback_session: Optional[aiohttp.ClientSession] = None
        # 这里只放通用的缓存，或者具体业务的缓存放到具体类中
        self.search_cache: Dict[str, Dict] = {}
        self.max_retries = max_retries
        self._session = session

    async def _request(
        self,
        url: str,
        method: str = "GET",
        params: Dict[str, Any] | None = None,
        json_data: Dict[str, Any] | None = None,
        is_json: bool = True,
    ) -> Any:
        """
        通用API请求函数，带限流和重试处理

        """
        last_exception: Exception | None = None

        for attempt in range(self.max_retries):
            async with self._rate_lock:
                now = time.time()
                gap = 1.1 - (now - self.last_request_time)
                if gap > 0:
                    await asyncio.sleep(gap)
                self.last_request_time = time.time()

            logger.info(
                f"Bangumi API请求 (尝试 {attempt + 1}/{self.max_retries}): {method} {url}"
            )

            try:
                # 优先使用外部注入的 Session
                session = (
                    self._session
                    if self._session and not self._session.closed
                    else await self._get_fallback_session()
                )
                request_context = (
                    session.post(
                        url,
                        json=json_data,
                        params=params,
                        proxy=self.proxy,
                        headers=self.headers,
                        timeout=self._timeout,
                    )
                    if method.upper() == "POST"
                    else session.get(
                        url,
                        params=params,
                        proxy=self.proxy,
                        headers=self.headers,
                        timeout=self._timeout,
                    )
                )

                async with request_context as response:
                    if response.status >= 500:
                        last_exception = BangumiApiError(
                            f"服务器错误 ({response.status})，尝试 {attempt + 1}/{self.max_retries}"
                        )
                        logger.warning(f"服务器返回错误状态码: {response.status}")
                        await asyncio.sleep(1.5)
                        continue
                    return await self._handle_response(response, is_json=is_json)

            except aiohttp.ClientError as e:
                logger.warning(f"网络请求失败: {e}")
                last_exception = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(1.5)
                else:
                    logger.error("达到最大重试次数，请求失败")

        raise BangumiApiError(f"请求失败，请稍后再试: {last_exception}")

    async def _get_fallback_session(self) -> aiohttp.ClientSession:
        """惰性创建并复用兜底 ClientSession。"""
        if self._fallback_session is None or self._fallback_session.closed:
            self._fallback_session = aiohttp.ClientSession(headers=self.headers)
        return self._fallback_session

    async def _handle_response(
        self, response: aiohttp.ClientResponse, is_json: bool = True
    ) -> Any:
        """
        处理api响应

        """
        if response.status == 200:
            if is_json:
                return await response.json()
            else:
                return await response.read()
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
