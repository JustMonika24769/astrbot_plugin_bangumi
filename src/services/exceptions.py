class NoSubjectFound(Exception):
    """找不到对应条目的异常类"""

    pass


class BangumiApiError(Exception):
    """Bangumi API请求错误的异常类"""

    pass


class BangumiRateLimitError(Exception):
    """API限流异常类"""

    pass
