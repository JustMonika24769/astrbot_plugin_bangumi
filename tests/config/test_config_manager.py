from unittest.mock import MagicMock

from astrbot_plugin_bangumi.src.config import ConfigManager


def _manager(values: dict[str, object]) -> ConfigManager:
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: values.get(key, default)
    return ConfigManager(config)


def test_get_int_accepts_int_and_numeric_string() -> None:
    assert _manager({"max_retries": 5}).get_max_retries() == 5
    assert _manager({"max_retries": "6"}).get_max_retries() == 6


def test_get_int_rejects_bool_and_invalid_string() -> None:
    assert _manager({"max_retries": True}).get_max_retries() == 3
    assert _manager({"max_retries": "bad"}).get_max_retries() == 3


def test_get_str_rejects_non_string_values() -> None:
    manager = _manager({"proxy_http": 123, "port": 7891})

    assert manager.get_proxy_http() == "127.0.0.1"
    assert manager.get_port() == "7890"


def test_user_agent_uses_config_value() -> None:
    assert _manager({"user_agent": "custom"}).get_user_agent() == "custom"


def test_save_config_swallows_supported_errors() -> None:
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: default
    config.save_config.side_effect = OSError("readonly")
    manager = ConfigManager(config)

    manager.save_config()

    config.save_config.assert_called_once()
