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


def test_proxy_defaults_do_not_imply_local_proxy() -> None:
    manager = _manager({})

    assert manager.get_proxy_http() == ""
    assert manager.get_port() == ""


def test_get_str_rejects_non_string_proxy_values() -> None:
    manager = _manager({"proxy_http": 123, "port": 7891})

    assert manager.get_proxy_http() == ""
    assert manager.get_port() == ""


def test_get_episode_card_template_reads_valid_config() -> None:
    manager = _manager({"episode_card_template": "editorial_digest"})

    assert manager.get_episode_card_template() == "editorial_digest"


def test_get_render_mode_defaults_to_pillow() -> None:
    assert _manager({}).get_render_mode() == "pillow"


def test_get_render_mode_accepts_new_modes_and_legacy_html() -> None:
    assert _manager({"render_mode": "playwright"}).get_render_mode() == "playwright"
    assert _manager({"render_mode": "RPC"}).get_render_mode() == "rpc"
    assert _manager({"render_mode": "html"}).get_render_mode() == "playwright"


def test_get_episode_card_template_falls_back_to_default() -> None:
    assert _manager({}).get_episode_card_template() == "cinematic_poster"
    assert (
        _manager(
            {"episode_card_template": "risograph_zine"}
        ).get_episode_card_template()
        == "cinematic_poster"
    )


def test_set_episode_card_template_updates_config_value() -> None:
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: default
    manager = ConfigManager(config)

    manager.set_episode_card_template("pastel_lightbox")

    config.__setitem__.assert_called_once_with(
        "episode_card_template", "pastel_lightbox"
    )


def test_user_agent_uses_config_value() -> None:
    assert _manager({"user_agent": "custom"}).get_user_agent() == "custom"


def test_save_config_swallows_supported_errors() -> None:
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: default
    config.save_config.side_effect = OSError("readonly")
    manager = ConfigManager(config)

    manager.save_config()

    config.save_config.assert_called_once()
