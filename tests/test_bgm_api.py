import sys
import os
import asyncio
from unittest.mock import MagicMock

# 1. Setup paths to include 'src'
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 2. Mock 'astrbot' dependency since it's likely not installed in this standalone test environment
try:
    import astrbot
except ImportError:
    # Create a mock module for astrbot
    astrbot_mock = MagicMock()
    sys.modules["astrbot"] = astrbot_mock

    # Create a mock module for astrbot.api
    astrbot_api_mock = MagicMock()
    sys.modules["astrbot.api"] = astrbot_api_mock

    # Set up a simple logger that prints to stdout
    mock_logger = MagicMock()
    mock_logger.info = lambda msg: print(f"[INFO] {msg}")
    mock_logger.warning = lambda msg: print(f"[WARN] {msg}")
    mock_logger.error = lambda msg: print(f"[ERROR] {msg}")
    astrbot_api_mock.logger = mock_logger

# 3. Import the renderer (now safe to import)
from src.render.subject_renderer import SubjectRenderer


async def main():
    # Sample data to render
    # You can modify this dictionary to test different content
    test_data = {
        "id": 332677,
        "name": "葬送のフリーレン",
        "name_cn": "葬送的芙莉莲",
        "type": 2,  # 2 = Anime
        "image_url": "https://lain.bgm.tv/pic/cover/l/c3/8c/332677_U3333.jpg",
        "summary": "在打倒了魔王的勇者一行人中，身为魔法使的芙莉莲同时也是长寿的精灵。她和伙伴们经历了长达十年的冒险，最后迎来了和平。...",
        "rating": {
            "score": 9.1,
            "rank": 1,
            "total": 12345,
            "count": {
                "1": 5,
                "2": 2,
                "3": 10,
                "4": 20,
                "5": 100,
                "6": 500,
                "7": 1500,
                "8": 4500,
                "9": 4000,
                "10": 1703,
            },
        },
        "collection": {"doing": 5678},
        "tags": [
            {"name": "奇幻"},
            {"name": "治愈"},
            {"name": "日常"},
            {"name": "冒险"},
        ],
        "air_date": "2023-09-29",
        "platform": "TV",
    }

    print("Initializing Renderer...")
    renderer = SubjectRenderer()

    output_filename = "subject_card_test.png"
    output_path = os.path.join(current_dir, output_filename)

    print(f"Rendering card to {output_path}...")

    image_bytes = await renderer.render_subject_card(
        data=test_data,
        headless=True,  # Set to False if you want to see the browser
        output_path=output_path,
        wait_time=1,  # Slight wait to ensure fonts/images load
    )

    if image_bytes:
        print(f"Success! Image saved to {output_path}")
    else:
        print("Failed to render image.")


if __name__ == "__main__":
    asyncio.run(main())
