from astrbot.api import logger
import asyncio


async def retry(func, retries: int = 3, delay: float = 1.0, *args, **kwargs) -> None:
    """
    通用重试方法
    :param func: 需要重试的异步函数
    :param retries: 重试次数
    :param delay: 重试间隔(秒)
    """
    last_exception = None
    for i in range(retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            logger.warning(f"渲染任务执行失败 (尝试 {i + 1}/{retries}): {e}")
            if i < retries - 1:
                await asyncio.sleep(delay)

    logger.error(f"渲染任务在 {retries} 次尝试后最终失败")
    raise last_exception
