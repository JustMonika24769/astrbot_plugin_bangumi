from pathlib import Path

from astrbot_plugin_bangumi.src.db import BangumiRepository


def _build_repository(tmp_path: Path) -> BangumiRepository:
    return BangumiRepository(str(tmp_path / "bangumi.db"))


def test_find_group_subscription_candidates_supports_similarity_fallback(
    tmp_path: Path,
) -> None:
    repository = _build_repository(tmp_path)
    repository.subscribe_subject("group_1", "1", "进击的巨人")
    repository.subscribe_subject("group_1", "2", "孤独摇滚")

    candidates = repository.find_group_subscription_candidates("group_1", "进机巨人")

    assert [subject.subject_id for subject in candidates] == ["1"]
