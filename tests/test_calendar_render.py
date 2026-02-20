import asyncio
import os
import sys
import base64
from pathlib import Path
from unittest.mock import MagicMock

# 设置路径
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Mock logger
mock_logger = MagicMock()
mock_logger.info = lambda msg: print(f"[INFO] {msg}")
mock_logger.warning = lambda msg: print(f"[WARN] {msg}")
mock_logger.error = lambda msg: print(f"[ERROR] {msg}")
sys.modules["astrbot.api"] = MagicMock(logger=mock_logger)

from src.render.calendar_renderer import CalendarRenderer

# 用户提供的样例数据
sample_data = [
    {
        "weekday": {"en": "Mon", "cn": "星期一", "ja": "月耀日", "id": 1},
        "items": [
            {
                "id": 443106,
                "name": "ゴールデンカムイ 最終章",
                "name_cn": "黄金神威 最终章",
                "images": {
                    "common": "http://lain.bgm.tv/pic/cover/c/7c/f1/443106_b4QP3.jpg"
                },
                "rating": {"score": 7.4},
                "rank": 1480,
            },
            {
                "id": 486763,
                "name": "姫様“拷问”の时间です 第2期",
                "name_cn": "公主大人“拷问”的时间到了 第二季",
                "images": {
                    "common": "http://lain.bgm.tv/pic/cover/c/13/79/486763_s49V9.jpg"
                },
                "rating": {"score": 7.1},
                "rank": 2200,
            },
        ],
    },
    {
        "weekday": {"en": "Tue", "cn": "星期二", "ja": "火耀日", "id": 2},
        "items": [
            {
                "id": 495531,
                "name": "ダーウィン事変",
                "name_cn": "达尔文事变",
                "images": {
                    "common": "http://lain.bgm.tv/pic/cover/c/41/af/495531_W0D3B.jpg"
                },
                "rating": {"score": 4.1},
                "rank": 9720,
            }
        ],
    },
    {
        "weekday": {"en": "Wed", "cn": "星期三", "ja": "水耀日", "id": 3},
        "items": [
            {
                "id": 975,
                "name": "ONE PIECE",
                "name_cn": "航海王",
                "images": {
                    "common": "http://lain.bgm.tv/pic/cover/c/92/97/975_YKuWd.jpg"
                },
                "rating": {"score": 8.3},
                "rank": 102,
            }
        ],
    },
    {"weekday": {"en": "Thu", "cn": "星期四", "ja": "木耀日", "id": 4}, "items": []},
    {"weekday": {"en": "Fri", "cn": "星期五", "ja": "金耀日", "id": 5}, "items": []},
    {"weekday": {"en": "Sat", "cn": "星期六", "ja": "土耀日", "id": 6}, "items": []},
    {"weekday": {"en": "Sun", "cn": "星期日", "ja": "日耀日", "id": 7}, "items": []},
]


async def main():
    renderer = CalendarRenderer()
    output_path = "tests/calendar_test.png"
    os.makedirs("tests", exist_ok=True)

    print("开始渲染放送表 (Base64 模式)...")
    base64_str = await renderer.render_calendar(
        calendar_data=sample_data
    )

    if base64_str:
        # 将 Base64 还原为文件以便预览
        image_bytes = base64.b64decode(base64_str)
        with open(output_path, "wb") as f:
            f.write(image_bytes)
        print(f"渲染并保存成功: {output_path}")
    else:
        print("渲染失败")


if __name__ == "__main__":
    asyncio.run(main())
