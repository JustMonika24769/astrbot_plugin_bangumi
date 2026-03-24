import asyncio
from collections.abc import Awaitable, Callable

from astrbot.api import logger


async def retry[T](
    func: Callable[..., Awaitable[T]],
    retries: int = 3,
    delay: float = 1.0,
    label: str = "任务",
    *args: object,
    **kwargs: object,
) -> T:
    """
    通用异步重试方法
    :param func: 需要重试的异步函数
    :param retries: 最大重试次数
    :param delay: 重试间隔(秒)
    :param label: 用于日志显示的标签
    :param args: 传递给 func 的位置参数
    :param kwargs: 传递给 func 的关键字参数
    :return: 异步函数的返回结果

    """
    last_exception: Exception | None = None
    for i in range(retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            logger.warning(f"{label} 执行失败 (尝试 {i + 1}/{retries}): {e}")
            if i < retries - 1:
                await asyncio.sleep(delay)

    logger.error(f"{label} 在 {retries} 次尝试后最终失败")
    if last_exception is None:
        raise RuntimeError(f"{label} 在 {retries} 次尝试后最终失败")
    raise last_exception
