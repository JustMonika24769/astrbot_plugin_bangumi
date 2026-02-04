import asyncio
import os
import sys
from unittest.mock import MagicMock

# 1. Setup paths to include 'src'
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 2. Mock 'astrbot' dependency
try:
    import astrbot
except ImportError:
    astrbot_mock = MagicMock()
    sys.modules["astrbot"] = astrbot_mock

    astrbot_api_mock = MagicMock()
    sys.modules["astrbot.api"] = astrbot_api_mock

    mock_logger = MagicMock()
    mock_logger.info = lambda msg: print(f"[INFO] {msg}")
    mock_logger.warning = lambda msg: print(f"[WARN] {msg}")
    mock_logger.error = lambda msg: print(f"[ERROR] {msg}")
    astrbot_api_mock.logger = mock_logger

# 3. Import the renderer
from src.render.subject_renderer import SubjectRenderer


async def main():
    # Sample data 1
    test_data_1 = {
        "id": 332677,
        "name": "葬送のフリーレン",
        "name_cn": "葬送的芙莉莲",
        "type": 2,
        "image_url": "https://lain.bgm.tv/pic/cover/l/c3/8c/332677_U3333.jpg",
        "summary": "Frieren",
        "rating": {"score": 9.1, "rank": 1, "total": 12345, "count": {"10": 1703}},
        "collection": {"doing": 5678},
        "tags": [{"name": "奇幻"}, {"name": "治愈"}],
        "air_date": "2023-09-29",
        "platform": "TV",
    }

    # Sample data 2
    test_data_2 = {
        "id": 1,
        "name": "Cowboy Bebop",
        "name_cn": "星际牛仔",
        "type": 2,
        "image_url": "https://lain.bgm.tv/pic/cover/l/f1/e5/1_sZ12P.jpg",
        "summary": "Cowboy Bebop",
        "rating": {"score": 9.2, "rank": 2, "total": 54321, "count": {"10": 5000}},
        "collection": {"doing": 123},
        "tags": [{"name": "科幻"}, {"name": "爵士"}],
        "air_date": "1998-04-03",
        "platform": "TV",
    }

    data_list = [test_data_1, test_data_2]

    print("Initializing Renderer...")
    renderer = SubjectRenderer()

    output_path_1 = os.path.join(current_dir, "batch_test_1.png")
    output_path_2 = os.path.join(current_dir, "batch_test_2.png")
    output_paths = [output_path_1, output_path_2]

    print("Batch rendering 2 cards...")

    results = await renderer.render_batch_subject_cards(
        data_list=data_list, output_paths=output_paths, headless=True, wait_time=1
    )

    print(f"Results: {results}")

    if all(results):
        print("Success! Both images rendered.")
        if os.path.exists(output_path_1) and os.path.exists(output_path_2):
            print(f"Files verified: {output_path_1}, {output_path_2}")
    else:
        print("Batch rendering failed.")


if __name__ == "__main__":
    asyncio.run(main())
