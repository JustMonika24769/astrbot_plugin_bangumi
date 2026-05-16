from unittest.mock import MagicMock

from astrbot_plugin_bangumi.src.config import ConfigManager


def test_get_render_mode_reads_config_value() -> None:
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: {
        "render_mode": "pillow",
    }.get(key, default)

    manager = ConfigManager(config)

    assert manager.get_render_mode() == "pillow"


def test_get_render_mode_invalid_value_falls_back_to_html() -> None:
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: {
        "render_mode": "unknown",
    }.get(key, default)

    manager = ConfigManager(config)

    assert manager.get_render_mode() == "html"
