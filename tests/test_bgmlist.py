from astrbot_plugin_bangumi.src.api.bgmlist import (
    _parse_broadcast_schedule,
    _parse_broadcast_time,
)


def test_broadcast_schedule_preserves_cst_date_and_time() -> None:
    schedule = _parse_broadcast_schedule("2026-07-15T15:30:00.000Z")

    assert schedule is not None
    assert schedule.broadcast_date == "2026-07-15"
    assert schedule.broadcast_time == "23:30"
    assert schedule.display == "首播 2026-07-15 · 每周三 23:30"
    assert _parse_broadcast_time("2026-07-15T15:30:00.000Z") == "23:30"


def test_broadcast_schedule_applies_cst_day_rollover() -> None:
    schedule = _parse_broadcast_schedule("2026-07-15T18:30:00.000Z")

    assert schedule is not None
    assert schedule.broadcast_date == "2026-07-16"
    assert schedule.broadcast_time == "02:30"
