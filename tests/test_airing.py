from datetime import date

import pytest

from astrbot_plugin_bangumi.src.airing import episode_schedule, weekly_schedule
from astrbot_plugin_bangumi.src.entities import Episode


def ep(day: str, *, kind: int = 0, number: int = 1) -> Episode:
    return Episode(number, 1, kind, number, number, air_date=day)


@pytest.mark.parametrize(
    ("premiere", "clock", "expected"),
    [
        ("2026-11-13", "23:30", "常规每周五 23:30（北京时间）"),
        ("2026-11-14", "02:00", "常规每周六 02:00（北京时间）"),
        (None, "23:30", "23:30（北京时间）· 星期待定"),
        ("invalid", None, "常规放送时间待定"),
    ],
)
def test_weekly_schedule_never_invents_missing_weekday(premiere, clock, expected):
    assert weekly_schedule(premiere, clock) == expected


def test_episode_schedule_keeps_actual_dates_across_a_skipped_week():
    result = episode_schedule(
        [ep("2026-11-06"), ep("2026-11-20", number=2)], date(2026, 11, 12)
    )
    assert result["this_week"] == []
    assert result["upcoming"] == [2]
    assert "可能停更" in result["message"]


def test_episode_schedule_includes_sunday_but_excludes_specials_and_unknown_dates():
    result = episode_schedule(
        [ep("2026-11-15"), ep("2026-11-12", kind=1, number=2), ep("", number=3)],
        date(2026, 11, 12),
    )
    assert result["this_week"] == [1]
    assert result["upcoming"] == [1]
    assert "临时停更" in result["message"]


@pytest.mark.parametrize(
    "episodes", [[], [ep("")], [ep("invalid")], [ep("2020-01-01")]]
)
def test_missing_future_dates_do_not_assert_hiatus_or_completion(episodes):
    result = episode_schedule(episodes, date(2026, 11, 12))
    assert result["upcoming"] == []
    assert "可能已完结、停更或资料未补全" in result["message"]
