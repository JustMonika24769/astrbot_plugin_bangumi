from astrbot_plugin_bangumi.src.plugin_config import DEFAULT_USER_AGENT, PluginConfig


def test_config_defaults_and_bounds() -> None:
    config = PluginConfig(
        {
            "search_limit": 100,
            "check_interval_minutes": 1,
            "request_timeout_seconds": "bad",
            "card_quality": 20,
        }
    )

    assert config.search_limit == 10
    assert config.check_interval_minutes == 5
    assert config.request_timeout_seconds == 25
    assert config.card_quality == 50
    assert config.user_agent == DEFAULT_USER_AGENT
    assert PluginConfig({"user_agent": ""}).user_agent == DEFAULT_USER_AGENT
    assert PluginConfig({"user_agent": "   "}).user_agent == DEFAULT_USER_AGENT


def test_config_prefers_full_proxy_and_supports_legacy_pair() -> None:
    assert PluginConfig({"proxy_url": "socks5://127.0.0.1:1080"}).proxy_url == (
        "socks5://127.0.0.1:1080"
    )
    assert (
        PluginConfig({"proxy_http": "127.0.0.1", "port": "7890"}).proxy_url
        == "http://127.0.0.1:7890"
    )


def test_config_boolean_parsing() -> None:
    config = PluginConfig(
        {
            "auto_translate_subject_summary": "yes",
            "auto_translate_episode_summary": "false",
        }
    )

    assert config.auto_translate_subject_summary is True
    assert config.auto_translate_episode_summary is False
