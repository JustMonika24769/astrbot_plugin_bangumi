class NoSubjectFound(Exception):
    """找不到对应条目的异常类"""

    pass


class BangumiApiError(Exception):
    """Bangumi API请求错误的异常类"""

    pass


class BangumiRateLimitError(Exception):
    """API限流异常类"""

    pass


class DatabaseError(Exception):
    """数据库操作异常:替换 repository 层宽泛的 except Exception,提供更精准的错误上下文"""

    pass


class SubscriptionError(Exception):
    """订阅业务异常:替换 subscription 服务层宽泛的 except Exception,提供更精准的错误反馈"""

    pass
