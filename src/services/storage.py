import sqlite3
import os
import logging
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

logger = logging.getLogger("astrbot")


class StorageManager:
    def __init__(self):
        # 获取插件数据目录
        data_dir = get_astrbot_data_path()
        plugin_data_dir = os.path.join(data_dir, "astrbot_plugin_bangumi")

        if not os.path.exists(plugin_data_dir):
            os.makedirs(plugin_data_dir)

        self.db_path = os.path.join(plugin_data_dir, "data.db")
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # 创建订阅表
            # group_id: 群组ID
            # subject_id: 条目ID
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    group_id TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (group_id, subject_id)
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"初始化数据库失败: {e}")

    def add_subscription(self, group_id: str, subject_id: str) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO subscriptions (group_id, subject_id) VALUES (?, ?)",
                (str(group_id), str(subject_id)),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"添加订阅失败: {e}")
            return False

    def get_subscriptions(self, group_id: str) -> list[str]:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT subject_id FROM subscriptions WHERE group_id = ?",
                (str(group_id),),
            )
            rows = cursor.fetchall()
            conn.close()
            return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"获取订阅失败: {e}")
            return []
