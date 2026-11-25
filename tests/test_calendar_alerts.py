"""Economic calendar message, 15-minute alerts, impact emojis, caching and fallbacks."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from conftest import calendar_fetch, ff, no_network, uk
from rdfx_bot.kinds.alerts import build_next_alert, due_alert_messages
from rdfx_bot.kinds.econ_calendar import build_calendar, impact_emoji
from rdfx_bot.models import RetryLater
from rdfx_bot.services.calendar_feed import CalendarService, FeedUnavailable
from rdfx_bot.textutil import validate_html

MONDAY = uk(2026, 11, 23, 8, 30)

SAMPLE = [
    ff("CPI y/y", "GBP", "2026-11-23T04:00:00-05:00", "High", "3.8%", "3.6%"),  # 09:00 UK
    ff("CPI m/m", "USD", "2026-11-23T08:30:00-05:00", "High", "0.3%", "0.2%"),  # 13:30 UK
    ff("Core CPI m/m", "USD", "2026-11-23T08:30:00-05:00", "High", "0.3%", ""),  # 13:30 UK, no previous
    ff("Federal Reserve Speaker", "USD", "2026-11-23T12:00:00-05:00", "Medium"),  # 17:00 UK
    ff("Consumer Sentiment", "USD", "2026-11-23T10:00:00-05:00", "Low", "50", "49"),  # dropped: low impact
    ff("GDP q/q", "CAD", "2026-11-23T01:30:00-05:00", "High", "0.5%", "0.4%"),  # dropped: currency
    ff("Bank Holiday", "JPY", "2026-11-23T00:00:00-05:00", "Holiday"),  # dropped: holiday
    ff("Tomorrow thing", "EUR", "2026-11-24T04:00:00-05:00", "Medium", "1", "2"),  # tomorrow
]


def service(cfg, now, items=SAMPLE, **kw):
    return CalendarService(cfg, now, persist=False, fetch=calendar_fetch(items), **kw)


# ---- parsing / filtering -----------------------------------------------------------

def test_only_high_and_medium_in_chosen_currencies_are_kept(cfg):
    titles = {e.title for e in service(cfg, MONDAY).events()}
    assert titles == {"CPI y/y", "CPI m/m", "Core CPI m/m", "Federal Reserve Speaker", "Tomorrow thing"}


def test_aud_is_included_and_jpy_is_not(cfg):
    items = [ff("RBA Rate Decision", "AUD", "2026-11-23T01:30:00-05:00", "High"), ff("BoJ Rate", "JPY", "2026-11-23T01:30:00-05:00", "High")]
    assert [e.title for e in service(cfg, MONDAY, items).events()] == ["RBA Rate Decision"]


def test_times_are_converted_to_uk_time(cfg):
    by_title = {e.title: e for e in service(cfg, MONDAY).events()}
    assert f"{by_title['CPI m/m'].start:%H:%M}" == "13:30"  # 08:30 New York
    assert f"{by_title['CPI y/y'].start:%H:%M}" == "09:00"


def test_currencies_are_configurable(cfg):
    cfg.sources["calendar"]["currencies"] = {"CAD": "🇨🇦"}
    assert [e.title for e in service(cfg, MONDAY).events()] == ["GDP q/q"]


def test_impact_emoji_mapping(cfg, make_ctx):
    ctx = make_ctx(MONDAY)
    assert impact_emoji(ctx, "High") == "🔴"
    assert impact_emoji(ctx, "Medium") == "🟠"
    assert impact_emoji(ctx, "high") == "🔴"


# ---- the 08:30 message -------------------------------------------------------------

def test_calendar_message_layout(cfg, make_ctx):
    ctx = make_ctx(MONDAY, calendar_fetcher=calendar_fetch(SAMPLE))
    text = build_calendar(ctx).text
    assert text.startswith("<b>📅 RDFX | ECONOMIC CALENDAR</b>\n\nKey events today (UK time):\n\n")
    assert "🔴 <b>09:00</b> 🇬🇧 <b>CPI y/y</b> · F 3.8% · P 3.6%" in text
    assert "🔴 <b>13:30</b> 🇺🇸 <b>CPI m/m</b> · F 0.3% · P 0.2%" in text
    assert "🟠 <b>17:00</b> 🇺🇸 Federal Reserve Speaker · F — · P —" in text
    assert "<b>Core CPI m/m</b> · F 0.3% · P —" in text
    assert "\n\n🔴" not in text.split("(UK time):\n\n", 1)[1].rsplit("\n\n", 1)[0]  # events are one tight block
    assert text.endswith("Expect volatility and wider spreads around these releases.")
    assert "Tomorrow thing" not in text and "Consumer Sentiment" not in text
    assert text.index("09:00") < text.index("13:30") < text.index("17:00")  # in time order
    assert validate_html(text) == []


def test_no_events_today_says_so_clearly(cfg, make_ctx):
    ctx = make_ctx(MONDAY, calendar_fetcher=calendar_fetch([]))
    text = build_calendar(ctx).text
    assert "No red or orange news events scheduled today. Stay patient and trade your plan." in text
    assert text.startswith("<b>📅 RDFX | ECONOMIC CALENDAR</b>")


def test_event_titles_cannot_inject_markup(cfg, make_ctx):
    items = [ff('CPI <a href="https://evil.example">click</a> & <script>x</script>', "USD", "2026-11-23T08:30:00-05:00", "High")]
    text = build_calendar(make_ctx(MONDAY, calendar_fetcher=calendar_fetch(items))).text
    assert "evil.example" not in text and "<script" not in text and "<a " not in text
    assert "&amp;" in text
    assert validate_html(text) == []


def test_feed_down_means_retry_not_a_false_no_events_message(cfg, make_ctx):
    with pytest.raises(RetryLater):
        build_calendar(make_ctx(MONDAY, calendar_fetcher=no_network))


def test_manual_overrides_are_used_but_do_not_pose_as_a_full_calendar(cfg, make_ctx):
    (cfg.root / "events.json").write_text(json.dumps([
        {"title": "Surprise Rate Decision", "currency": "gbp", "impact": "high", "datetime": "2026-11-23T14:00", "forecast": "4%", "previous": "4%"},
        {"title": "missing fields"},
    ]))
    ctx = make_ctx(uk(2026, 11, 23, 13, 50), calendar_fetcher=no_network)
    events = ctx.calendar.events()
    assert [e.title for e in events] == ["Surprise Rate Decision"]
    assert f"{events[0].start:%H:%M}" == "14:00"  # naive times are read as UK time
    assert len(due_alert_messages(ctx)) == 1  # alerts work from overrides alone
    with pytest.raises(RetryLater):  # but the daily calendar will not claim a complete list
        build_calendar(ctx)


# ---- caching / fallbacks -----------------------------------------------------------

def test_feed_fetched_at_most_once_an_hour(cfg):
    calls = []
    for minutes, expected in ((0, 1), (30, 1), (59, 1), (61, 2)):
        now = MONDAY + timedelta(minutes=minutes)
        CalendarService(cfg, now, persist=True, fetch=calendar_fetch(SAMPLE, calls)).events()
        assert len(calls) == expected, minutes


def test_failed_fetch_is_not_retried_for_15_minutes_and_stale_copy_is_used(cfg):
    calls = []
    CalendarService(cfg, MONDAY, persist=True, fetch=calendar_fetch(SAMPLE, calls)).events()  # good copy
    assert len(calls) == 1

    def failing(url):
        calls.append(url)
        raise OSError("down")

    backups = 1 + len(cfg.sources["calendar"].get("backup_urls") or [])  # main address + each backup
    later = MONDAY + timedelta(minutes=70)
    svc = CalendarService(cfg, later, persist=True, fetch=failing)
    assert len(svc.events()) == 5 and svc.status == "stale"
    assert len(calls) == 1 + backups
    CalendarService(cfg, later + timedelta(minutes=5), persist=True, fetch=failing).events()
    assert len(calls) == 1 + backups  # inside the 15 minute back-off: no new request
    CalendarService(cfg, later + timedelta(minutes=16), persist=True, fetch=failing).events()
    assert len(calls) == 1 + 2 * backups


def test_stale_copy_is_dropped_after_max_stale_hours(cfg):
    CalendarService(cfg, MONDAY, persist=True, fetch=calendar_fetch(SAMPLE)).events()
    with pytest.raises(FeedUnavailable):
        CalendarService(cfg, MONDAY + timedelta(hours=49), persist=True, fetch=no_network).events()


def test_garbage_from_feed_is_handled(cfg):
    svc = CalendarService(cfg, MONDAY, persist=False, fetch=lambda url: b"<html>Request Denied</html>")
    with pytest.raises(FeedUnavailable):
        svc.events()


# ---- 15 minute alerts --------------------------------------------------------------

CPI = [ff("US CPI y/y", "USD", "2026-11-23T08:30:00-05:00", "High", "3.1%", "3.0%")]  # 13:30 UK


def alerts_at(make_ctx, now, items=CPI):
    ctx = make_ctx(now, calendar_fetcher=calendar_fetch(items))
    return ctx, due_alert_messages(ctx)


def test_alert_fires_inside_the_15_minute_window_with_exact_wording(make_ctx):
    _ctx, msgs = alerts_at(make_ctx, uk(2026, 11, 23, 13, 15))
    assert len(msgs) == 1
    assert msgs[0].text == (
        "<b>⏰ RDFX | NEWS ALERT</b>\n\n"
        "<b>🔴 🇺🇸 US CPI y/y</b>\n"
        "Releasing in <b>15 minutes</b> (13:30 UK)\n\n"
        "Forecast: 3.1% · Previous: 3.0%\n\n"
        "Expect volatility and wider spreads."
    )
    assert validate_html(msgs[0].text) == []


def test_alert_is_honest_about_time_left_when_the_run_is_late(make_ctx):
    assert "Releasing in <b>10 minutes</b>" in alerts_at(make_ctx, uk(2026, 11, 23, 13, 20))[1][0].text
    assert "Releasing in <b>2 minutes</b>" in alerts_at(make_ctx, uk(2026, 11, 23, 13, 28))[1][0].text


def test_no_alert_too_early_or_for_events_already_released(make_ctx):
    assert alerts_at(make_ctx, uk(2026, 11, 23, 13, 14))[1] == []  # 16 minutes away
    assert alerts_at(make_ctx, uk(2026, 11, 23, 13, 30))[1] == []  # releasing right now
    assert alerts_at(make_ctx, uk(2026, 11, 23, 13, 29, 30))[1] == []  # under a minute left
    assert alerts_at(make_ctx, uk(2026, 11, 23, 14, 0))[1] == []  # already released


def test_alert_sent_once_per_event(make_ctx):
    ctx, msgs = alerts_at(make_ctx, uk(2026, 11, 23, 13, 15))
    for key in msgs[0].dedupe_keys:
        ctx.state.mark_alerted(key, ctx.now)
    assert due_alert_messages(ctx) == []


def test_medium_events_get_yellow_and_one_alert_per_time_slot(make_ctx):
    items = [ff("Federal Reserve Speaker", "USD", "2026-11-23T12:00:00-05:00", "Medium")]  # 17:00 UK
    msgs = alerts_at(make_ctx, uk(2026, 11, 23, 16, 45), items)[1]
    assert "🟠 🇺🇸 Federal Reserve Speaker" in msgs[0].text
    assert "Forecast: — · Previous: —" in msgs[0].text


def test_simultaneous_events_become_one_alert_by_default(make_ctx):
    items = [
        ff("CPI m/m", "USD", "2026-11-23T08:30:00-05:00", "High", "0.3%", "0.2%"),
        ff("Core CPI m/m", "USD", "2026-11-23T08:30:00-05:00", "High", "0.3%", "0.3%"),
        ff("Unemployment Claims", "USD", "2026-11-23T08:30:00-05:00", "Medium", "220K", "218K"),
    ]
    msgs = alerts_at(make_ctx, uk(2026, 11, 23, 13, 15), items)[1]
    assert len(msgs) == 1 and len(msgs[0].dedupe_keys) == 3
    assert msgs[0].text.count("Forecast:") == 3 and msgs[0].text.count("Releasing in") == 1


def test_grouping_can_be_switched_off(cfg, make_ctx):
    cfg.schedule["alerts"]["group_same_time"] = False
    items = [ff("A", "USD", "2026-11-23T08:30:00-05:00", "High"), ff("B", "USD", "2026-11-23T08:30:00-05:00", "High")]
    assert len(alerts_at(make_ctx, uk(2026, 11, 23, 13, 15), items)[1]) == 2


def test_no_events_means_no_alerts(make_ctx):
    assert alerts_at(make_ctx, uk(2026, 11, 23, 13, 15), [])[1] == []


def test_alerts_respect_weekends_christmas_and_the_switch(cfg, make_ctx):
    sat = [ff("X", "USD", "2026-11-21T08:30:00-05:00", "High")]
    assert alerts_at(make_ctx, uk(2026, 11, 21, 13, 15), sat)[1] == []
    xmas = [ff("X", "USD", "2026-12-25T08:30:00-05:00", "High")]
    assert alerts_at(make_ctx, uk(2026, 12, 25, 13, 15), xmas)[1] == []
    cfg.schedule["alerts"]["enabled"] = False
    assert alerts_at(make_ctx, uk(2026, 11, 23, 13, 15))[1] == []


def test_alerts_never_crash_when_the_feed_is_down(make_ctx):
    ctx = make_ctx(uk(2026, 11, 23, 13, 15), calendar_fetcher=no_network)
    assert due_alert_messages(ctx) == []


def test_manual_alert_uses_next_event_or_a_sample_in_dry_runs(make_ctx):
    # dry_run=True everywhere so no calendar cache is written between the contexts
    ctx = make_ctx(uk(2026, 11, 23, 9, 0), calendar_fetcher=calendar_fetch(CPI), dry_run=True)
    assert "US CPI y/y" in build_next_alert(ctx).text
    empty = make_ctx(uk(2026, 11, 23, 9, 0), calendar_fetcher=calendar_fetch([]), dry_run=True)
    assert "SAMPLE" in build_next_alert(empty).text
    live_empty = make_ctx(uk(2026, 11, 23, 9, 0), calendar_fetcher=calendar_fetch([]))
    with pytest.raises(RetryLater):
        build_next_alert(live_empty)


def test_big_movers_are_bold_but_speeches_are_not(cfg, make_ctx):
    from rdfx_bot.kinds.econ_calendar import is_big_mover

    ctx = make_ctx(uk(2026, 11, 23, 8, 30), dry_run=True)
    for title in ("US CPI y/y", "Non-Farm Employment Change", "FOMC Statement", "Federal Funds Rate", "Final GDP q/q", "Unemployment Rate", "Official Bank Rate"):
        assert is_big_mover(ctx, title), title
    for title in ("FOMC Member Waller Speaks", "Flash Manufacturing PMI", "Retail Sales m/m"):
        assert not is_big_mover(ctx, title), title


def test_backup_calendar_address_is_used_when_the_main_one_fails(cfg):
    main = cfg.sources["calendar"]["url"]
    asked = []

    def fetch(url):
        asked.append(url)
        if url == main:
            raise OSError("main host down")
        return json.dumps(SAMPLE).encode()

    svc = CalendarService(cfg, MONDAY, persist=False, fetch=fetch)
    assert len(svc.events()) == 5 and svc.status == "live"
    assert asked[0] == main and len(asked) == 2
