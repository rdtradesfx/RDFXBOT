"""UK-time scheduling: weekends, GMT/BST, catch-up windows, offsets, per-day entries."""

from __future__ import annotations

from datetime import time

import pytest

from conftest import uk, utc
from rdfx_bot.scheduler import due_slots, parse_hhmm


def ids(cfg, now):
    return [s.entry_id for s in due_slots(now, cfg.schedule, cfg.settings, cfg.tz)]


def test_weekend_has_no_sends(cfg):
    for now in (uk(2026, 11, 21, 8, 0), uk(2026, 11, 22, 8, 0), uk(2026, 11, 21, 0, 0), uk(2026, 11, 22, 13, 0)):
        assert ids(cfg, now) == []


def test_weekday_slots_fire_at_their_uk_times(cfg):
    monday = {
        (0, 0): "asia_open", (7, 0): "daily_news", (8, 0): "london_open", (8, 30): "economic_calendar",
        (13, 0): "newyork_open", (11, 0): "vip_am",
    }
    for (hour, minute), expected in monday.items():
        assert expected in ids(cfg, uk(2026, 11, 23, hour, minute)), expected


def test_overlap_is_switched_off_in_the_shipped_schedule(cfg):
    assert cfg.schedule["messages"]["overlap"]["enabled"] is False
    for minute in (0, 3, 10):
        assert "overlap" not in ids(cfg, uk(2026, 11, 23, 13, minute))


def test_overlap_is_staggered_by_three_minutes_when_switched_on(cfg):
    cfg.schedule["messages"]["overlap"]["enabled"] = True
    assert "newyork_open" in ids(cfg, uk(2026, 11, 23, 13, 0))
    assert "overlap" not in ids(cfg, uk(2026, 11, 23, 13, 2))
    assert "overlap" in ids(cfg, uk(2026, 11, 23, 13, 3))


def test_overlap_offset_zero_is_allowed(cfg):
    cfg.schedule["messages"]["overlap"]["enabled"] = True
    cfg.schedule["messages"]["overlap"]["offset_minutes"] = 0
    assert {"newyork_open", "overlap"} <= set(ids(cfg, uk(2026, 11, 23, 13, 0)))


def test_funnel_days(cfg):
    assert "vip_am" in ids(cfg, uk(2026, 11, 23, 11, 0))  # Mon
    assert "mentorship_am" not in ids(cfg, uk(2026, 11, 23, 11, 0))
    assert "mentorship_am" in ids(cfg, uk(2026, 11, 24, 11, 0))  # Tue
    assert "vip_am" not in ids(cfg, uk(2026, 11, 24, 11, 0))
    assert "vip_am" in ids(cfg, uk(2026, 11, 27, 11, 0))  # Fri
    assert "social_pm" in ids(cfg, uk(2026, 11, 25, 18, 0))  # Wed
    assert "social_pm" not in ids(cfg, uk(2026, 11, 24, 18, 0))  # not Tue


def test_selling_posts_stay_under_20_percent(cfg):
    """One funnel a day at most, one social a week: 6 selling posts a week against 25 fixed useful ones (plus alerts)."""
    selling = fixed = 0
    for day in range(23, 28):  # Mon..Fri
        seen = set()
        for hour in range(0, 24):
            for minute in range(0, 60, 5):
                seen.update(ids(cfg, uk(2026, 11, day, hour, minute)))
        kinds = [cfg.schedule["messages"][i]["kind"] for i in seen]
        assert sum(k.startswith("funnel") for k in kinds) <= 1
        selling += sum(k.startswith("funnel") or k == "social" for k in kinds)
        fixed += sum(not (k.startswith("funnel") or k == "social") for k in kinds)
    assert selling / (selling + fixed) < 0.20


# ---- GMT / BST ---------------------------------------------------------------------

def test_london_open_follows_bst(cfg):
    # Summer (BST = UTC+1): 08:00 UK is 07:00 UTC
    assert "london_open" in ids(cfg, utc(2026, 7, 6, 7, 0))
    assert "london_open" not in ids(cfg, utc(2026, 7, 6, 8, 0))
    # Winter (GMT): 08:00 UK is 08:00 UTC
    assert "london_open" in ids(cfg, utc(2026, 11, 23, 8, 0))
    assert "london_open" not in ids(cfg, utc(2026, 11, 23, 7, 0))


def test_midnight_uk_falls_on_previous_utc_day_in_summer(cfg):
    # A plain UK-time entry (no tz): UK midnight in BST is 23:00 UTC the day before.
    entry = {"kind": "asia", "enabled": True, "times": ["00:00"]}
    cfg.schedule["messages"]["asia_open"] = entry
    assert "asia_open" in ids(cfg, utc(2026, 7, 5, 23, 0))  # Monday 00:00 BST
    assert "asia_open" in ids(cfg, utc(2026, 11, 23, 0, 0))  # Monday 00:00 GMT


# ---- session times follow the real market opens through every clocks change ----
def test_asian_open_is_tokyo_9am_so_0000_in_winter_and_0100_in_summer(cfg):
    assert "asia_open" in ids(cfg, uk(2026, 11, 23, 0, 0))   # winter (GMT)
    assert "asia_open" not in ids(cfg, uk(2026, 11, 23, 1, 0))
    assert "asia_open" in ids(cfg, uk(2026, 7, 6, 1, 0))     # summer (BST): 01:00 UK
    assert "asia_open" not in ids(cfg, uk(2026, 7, 6, 0, 0))


def test_london_stays_0800_uk_all_year(cfg):
    for day in ((2026, 11, 23), (2026, 7, 6)):
        assert "london_open" in ids(cfg, uk(*day, 8, 0))


def test_new_york_open_is_0800_new_york_time(cfg):
    # Normal winter and normal summer: 13:00 UK.
    assert "newyork_open" in ids(cfg, uk(2026, 11, 23, 13, 0))
    assert "newyork_open" in ids(cfg, uk(2026, 7, 6, 13, 0))
    # The gaps when the US and UK clocks are out of step by an hour: 12:00 UK.
    assert "newyork_open" in ids(cfg, uk(2027, 3, 15, 12, 0))    # US already on summer time, UK not yet
    assert "newyork_open" not in ids(cfg, uk(2027, 3, 15, 13, 0))
    assert "newyork_open" in ids(cfg, uk(2026, 10, 26, 12, 0))   # UK back on winter time, US not yet
    assert "newyork_open" not in ids(cfg, uk(2026, 10, 26, 13, 0))


def test_tz_sessions_still_obey_weekends_and_blocked_dates(cfg):
    assert ids(cfg, uk(2026, 11, 22, 0, 0)) == []                 # Sunday
    assert ids(cfg, uk(2026, 12, 25, 13, 0)) == []                # Christmas Day (a Friday)
    assert "newyork_open" in ids(cfg, uk(2026, 12, 24, 13, 0))


def test_unknown_timezone_skips_that_entry_only(cfg):
    cfg.schedule["messages"]["asia_open"]["tz"] = "Mars/Olympus"
    assert "asia_open" not in ids(cfg, uk(2026, 11, 23, 0, 0))
    assert "london_open" in ids(cfg, uk(2026, 11, 23, 8, 0))


def test_spring_clock_change_week(cfg):
    # Clocks go forward Sunday 29 March 2026.
    assert "london_open" in ids(cfg, utc(2026, 3, 27, 8, 0))  # Friday, GMT
    assert "london_open" in ids(cfg, utc(2026, 3, 30, 7, 0))  # Monday, BST
    assert "london_open" not in ids(cfg, utc(2026, 3, 30, 8, 0))


def test_autumn_clock_change_week(cfg):
    # Clocks go back Sunday 25 October 2026.
    assert "london_open" in ids(cfg, utc(2026, 10, 23, 7, 0))  # Friday, BST
    assert "london_open" in ids(cfg, utc(2026, 10, 26, 8, 0))  # Monday, GMT
    assert "london_open" not in ids(cfg, utc(2026, 10, 26, 7, 0))


def test_result_does_not_depend_on_the_input_timezone(cfg):
    assert ids(cfg, uk(2026, 7, 6, 8, 0)) == ids(cfg, utc(2026, 7, 6, 7, 0))


# ---- catch-up window ---------------------------------------------------------------

def test_catch_up_window_default_45_minutes(cfg):
    assert "london_open" in ids(cfg, uk(2026, 11, 23, 8, 44))
    assert "london_open" not in ids(cfg, uk(2026, 11, 23, 8, 45))
    assert "london_open" not in ids(cfg, uk(2026, 11, 23, 7, 59))  # never early


def test_catch_up_window_can_be_overridden_per_entry(cfg):
    cfg.schedule["messages"]["london_open"]["catch_up_minutes"] = 10
    assert "london_open" in ids(cfg, uk(2026, 11, 23, 8, 9))
    assert "london_open" not in ids(cfg, uk(2026, 11, 23, 8, 10))


def test_late_evening_slot_delayed_past_midnight_still_goes_out(cfg):
    schedule = {"catch_up_minutes": 45, "messages": {"late": {"kind": "london", "times": ["23:50"]}}}
    slots = due_slots(uk(2026, 11, 24, 0, 10), schedule, cfg.settings, cfg.tz)  # Tuesday 00:10
    assert [s.entry_id for s in slots] == ["late"]
    assert slots[0].slot_date.isoformat() == "2026-11-23"


def test_disabled_entries_never_fire(cfg):
    cfg.schedule["messages"]["london_open"]["enabled"] = False
    assert "london_open" not in ids(cfg, uk(2026, 11, 23, 8, 0))


def test_bad_entry_is_skipped_not_fatal(cfg):
    cfg.schedule["messages"]["broken"] = {"kind": "london", "times": ["25:99"]}
    assert "london_open" in ids(cfg, uk(2026, 11, 23, 8, 0))


def test_active_days_setting_is_a_global_limit(cfg):
    cfg.settings["active_days"] = ["mon"]
    assert ids(cfg, uk(2026, 11, 24, 8, 0)) == []  # Tuesday
    assert "london_open" in ids(cfg, uk(2026, 11, 23, 8, 0))


@pytest.mark.parametrize("value,expected", [("08:00", time(8, 0)), ("8:05", time(8, 5)), (780, time(13, 0)), (0, time(0, 0))])
def test_parse_hhmm(value, expected):
    assert parse_hhmm(value) == expected


@pytest.mark.parametrize("value", ["25:00", "8", "noon", "12:60"])
def test_parse_hhmm_rejects_nonsense(value):
    with pytest.raises(ValueError):
        parse_hhmm(value)
