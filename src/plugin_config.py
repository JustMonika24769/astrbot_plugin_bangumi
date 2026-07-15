from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

DEFAULT_USER_AGENT = (
    "AstrBot-Bangumi-Plugin/v2.0.3 "
    "(https://github.com/united-pooh/astrbot_plugin_bangumi)"
)


class PluginConfig:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    def _text(self, key: str, default: str = "") -> str:
        value = self._config.get(key, default)
        return str(value).strip() if value is not None else default

    def _integer(self, key: str, default: int, low: int, high: int) -> int:
        try:
            value = int(self._config.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value))

    def _boolean(self, key: str, default: bool = False) -> bool:
        value = self._config.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @property
    def access_token(self) -> str:
        return self._text("access_token")

    @property
    def user_agent(self) -> str:
        return self._text("user_agent") or DEFAULT_USER_AGENT

    @property
    def proxy_url(self) -> str | None:
        configured = self._text("proxy_url")
        if configured:
            return configured

        host = self._text("proxy_http")
        port = self._text("port")
        if not host or not port:
            return None
        parsed = urlsplit(host if "://" in host else f"//{host}")
        scheme = parsed.scheme or "http"
        netloc = parsed.netloc
        if not netloc:
            return None
        host_part = netloc.rsplit("@", maxsplit=1)[-1]
        has_port = "]:" in host_part if host_part.startswith("[") else ":" in host_part
        if not has_port:
            netloc = f"{netloc}:{port}"
        return urlunsplit((scheme, netloc, parsed.path, parsed.query, parsed.fragment))

    @property
    def search_limit(self) -> int:
        return self._integer("search_limit", 5, 1, 10)

    @property
    def check_interval_minutes(self) -> int:
        return self._integer("check_interval_minutes", 15, 5, 180)

    @property
    def request_timeout_seconds(self) -> int:
        return self._integer("request_timeout_seconds", 25, 5, 120)

    @property
    def max_retries(self) -> int:
        return self._integer("max_retries", 3, 1, 6)

    @property
    def card_quality(self) -> int:
        return self._integer("card_quality", 88, 50, 100)

    @property
    def auto_translate_subject_summary(self) -> bool:
        return self._boolean("auto_translate_subject_summary")

    @property
    def auto_translate_episode_summary(self) -> bool:
        return self._boolean("auto_translate_episode_summary")
