import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

# 将项目根目录添加到 sys.path 以便导入 src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.services.storage import BangumiSubject, StorageManager


class TestStorageManager(unittest.TestCase):
    def setUp(self):
        # 创建临时目录用于测试数据库
        self.test_dir = tempfile.mkdtemp()

        # Mock get_astrbot_data_path
        self.patcher = patch(
            "src.services.storage.get_astrbot_data_path", return_value=self.test_dir
        )
        self.mock_get_path = self.patcher.start()

        # 初始化 StorageManager
        self.storage = StorageManager()

    def tearDown(self):
        # 停止 mock
        self.patcher.stop()
        # 清理临时目录
        shutil.rmtree(self.test_dir)

    def test_save_and_update_subject(self):
        """测试保存和更新番剧信息"""
        subject_id = "12345"
        name = "Test Anime"

        # 1. 保存新番剧
        result = self.storage.update_subject(
            subject_id=subject_id,
            name=name,
            air_date="2023-10-01",
            total_episodes=12,
            current_episode=1,
        )
        self.assertTrue(result, "Should successfully save new subject")

        # 验证是否保存成功
        session = self.storage.Session()
        subject = session.query(BangumiSubject).filter_by(subject_id=subject_id).first()
        self.assertIsNotNone(subject)
        self.assertEqual(subject.name, name)
        self.assertEqual(subject.current_episode, 1)
        session.close()

        # 2. 更新番剧信息 (例如更新名称或总集数)
        new_name = "Test Anime Updated"
        result = self.storage.update_subject(
            subject_id=subject_id, name=new_name, total_episodes=13
        )
        self.assertTrue(result, "Should successfully update subject")

        # 验证更新
        session = self.storage.Session()
        subject = session.query(BangumiSubject).filter_by(subject_id=subject_id).first()
        self.assertEqual(subject.name, new_name)
        self.assertEqual(subject.total_episodes, 13)
        # current_episode 应该保持不变，因为我们没传
        self.assertEqual(subject.current_episode, 1)
        session.close()

    def test_subscription_flow(self):
        """测试订阅流程：添加订阅 -> 查询订阅 -> 查询订阅者"""
        group_id_1 = "group_1"
        group_id_2 = "group_2"
        subject_id = "999"

        # 先保存番剧信息 (虽然 add_subscription 会自动处理不存在的 subject，但最好先有)
        self.storage.update_subject(subject_id, "My Favorite Anime")

        # 1. 添加订阅
        self.storage.add_subscription(group_id_1, subject_id)
        self.storage.add_subscription(group_id_2, subject_id)

        # 2. 验证某群组的订阅列表
        subs_1 = self.storage.get_subscriptions(group_id_1)
        self.assertIn(subject_id, subs_1)

        subs_2 = self.storage.get_subscriptions(group_id_2)
        self.assertIn(subject_id, subs_2)

        # 3. 验证某番剧的订阅群组
        subscribers = self.storage.get_subject_subscribers(subject_id)
        self.assertIn(group_id_1, subscribers)
        self.assertIn(group_id_2, subscribers)
        self.assertEqual(len(subscribers), 2)

    def test_monitored_subjects(self):
        """测试获取监控列表"""
        # 添加两个番剧和订阅
        self.storage.update_subject("1001", "Anime 1")
        self.storage.add_subscription("g1", "1001")

        self.storage.update_subject("1002", "Anime 2")
        self.storage.add_subscription("g1", "1002")

        # 获取监控列表
        subjects = self.storage.get_monitored_subjects()
        self.assertEqual(len(subjects), 2)

        ids = [s.subject_id for s in subjects]
        self.assertIn("1001", ids)
        self.assertIn("1002", ids)

    def test_update_episode(self):
        """测试更新集数"""
        sid = "555"
        self.storage.update_subject(sid, "Episodic Anime", current_episode=5)

        # 更新集数
        self.storage.update_subject_episode(sid, 6)

        # 验证
        session = self.storage.Session()
        subject = session.query(BangumiSubject).filter_by(subject_id=sid).first()
        self.assertEqual(subject.current_episode, 6)
        session.close()


if __name__ == "__main__":
    unittest.main()
