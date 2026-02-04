from pathlib import Path

import yaml
from astrbot.api import AstrBotConfig, logger


class ConfigManager:
    def __init__(self, config: AstrBotConfig):
        self.config = config

    def get_access_token(self) -> str:
        """
        获取bangumi的access_token
        """
        return self.config.get("access_token", "")

    def get_user_agent(self) -> str:
        user_agent = self.config.get("user_agent", "")
        if user_agent == "":
            with open(
                f"{Path(__file__).resolve().parent.parent.parent}/metadata.yaml", "r"
            ) as f:
                metadata = yaml.safe_load(f)
                user_agent = f"AstrBot-Bangumi-Plugin/{metadata['version']} (https://github.com/united-pooh/astrbot_plugin_bangumi)"
        return user_agent

    def get_max_fuzzy_results(self) -> int:
        return self.config.get("max_fuzzy_results", 5)

    def get_proxy_http(self) -> str:
        return self.config.get("proxy_http", "127.0.0.1")

    def get_port(self) -> str:
        return self.config.get("port", "7890")

    def get_max_retries(self) -> int:
        return self.config.get("max_retries", 3)

    def save_config(self):
        """
        保存bgm插件配置到配置文件中, 并重新加载配置
        """
        try:
            self.config.save_config()
            logger.info("配置已保存")
        except Exception as e:
            logger.error(f"保存bgm插件配置失败: {e}")
