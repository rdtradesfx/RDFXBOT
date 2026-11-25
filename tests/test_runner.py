"""End to end: what gets sent, once, and what is remembered."""

from __future__ import annotations

import json

from conftest import FakeSender, calendar_fetch, ff, no_network, rss_xml, uk
from rdfx_bot.runner import ConsoleSender, run_manual, run_preview, run_scheduled
from rdfx_bot.state import State


def run(make_ctx, now, sender, **kw):
    return run_scheduled(make_ctx(now, **kw), sender, sleep=lambda s: None)


def test_slot_is_sent_once_then_deduplicated(make_ctx, cfg):
    sender = FakeSender()
    run(make_ctx, uk(2026, 11, 23, 8, 0), sender)
    assert sender.kinds == ["london"]
    run(make_ctx, uk(2026, 11, 23, 8, 5), sender)  # next cron tick
    run(make_ctx, uk(2026, 11, 23, 8, 40), sender)  # much later, still in the window
    assert sender.kinds == ["london"]
    saved = json.loads((cfg.root / "state" / "sent.json").read_text())
    assert list(saved["sent"]) == ["london_open@2026-11-23T08:00"]


def test_delayed_run_inside_window_still_sends_but_outside_does_not(make_ctx):
    late, stale = FakeSender(), FakeSender()
    run(make_ctx, uk(2026, 11, 23, 8, 31), late)
    assert late.kinds == ["london"]
    run(make_ctx, uk(2026, 11, 23, 9, 30), stale)  # an hour and a half late
    assert stale.kinds == []


def test_failed_send_is_not_marked_and_retries_next_run(make_ctx):
    run(make_ctx, uk(2026, 11, 23, 8, 0), FakeSender(fail=True))
    again = FakeSender()
    run(make_ctx, uk(2026, 11, 23, 8, 5), again)
    assert again.kinds == ["london"]


def test_two_messages_in_one_run_are_spaced_by_the_gap(make_ctx, cfg):
    sleeps = []
    sender = FakeSender()
    cfg.schedule["messages"]["overlap"]["enabled"] = True  # the shipped schedule has it switched off
    ctx = make_ctx(uk(2026, 11, 23, 13, 5))  # delayed run: New York AND overlap are both due
    run_scheduled(ctx, sender, sleep=sleeps.append)
    assert sender.kinds == ["newyork", "overlap"]
    assert sleeps == [4.0]


def test_kill_switch_stops_live_sends_but_not_dry_runs(make_ctx, cfg):
    cfg.settings["enabled"] = False
    live = FakeSender()
    run(make_ctx, uk(2026, 11, 23, 8, 0), live)
    assert live.messages == []
    assert run_manual(make_ctx(uk(2026, 11, 23, 8, 0)), live, "london").sent == []
    dry = FakeSender()
    run_scheduled(make_ctx(uk(2026, 11, 23, 8, 0), dry_run=True), dry, sleep=lambda s: None)
    assert dry.kinds == ["london"]


def test_dry_run_changes_no_state(make_ctx, cfg):
    sender = FakeSender()
    run(make_ctx, uk(2026, 11, 23, 8, 0), sender, dry_run=True)
    assert sender.kinds == ["london"]
    assert not (cfg.root / "state" / "sent.json").exists()
    assert not (cfg.root / "state" / "calendar_cache.json").exists()


def test_unknown_kind_is_logged_not_fatal(make_ctx, cfg):
    cfg.schedule["messages"]["typo"] = {"kind": "londn", "times": ["08:00"]}
    sender = FakeSender()
    result = run(make_ctx, uk(2026, 11, 23, 8, 0), sender)
    assert sender.kinds == ["london"]
    assert result.ok


def test_slot_waits_for_data_then_sends_inside_window(make_ctx):
    """The 08:30 calendar needs the feed: no feed = nothing sent and nothing marked; feed back = sent."""
    sender = FakeSender()
    run(make_ctx, uk(2026, 11, 23, 8, 30), sender)  # feed down (the late London message goes out, calendar cannot)
    assert "calendar" not in sender.kinds
    items = [ff("CPI m/m", "USD", "2026-11-23T08:30:00-05:00", "High", "0.3%", "0.2%")]
    # After a failed fetch the bot waits 15 minutes (retry_minutes) before asking the feed again.
    run(make_ctx, uk(2026, 11, 23, 8, 40), sender, calendar_fetcher=calendar_fetch(items))
    assert "calendar" not in sender.kinds
    run(make_ctx, uk(2026, 11, 23, 8, 45), sender, calendar_fetcher=calendar_fetch(items))  # still inside the 45 min window
    assert sender.kinds.count("calendar") == 1
    run(make_ctx, uk(2026, 11, 23, 8, 50), sender, calendar_fetcher=calendar_fetch(items))
    assert sender.kinds.count("calendar") == 1  # never twice


def test_news_alert_is_sent_once_across_runs(make_ctx):
    items = [ff("US CPI y/y", "USD", "2026-11-23T11:30:00-05:00", "High", "3.1%", "3.0%")]  # 16:30 UK
    sender = FakeSender()
    run(make_ctx, uk(2026, 11, 23, 16, 15), sender, calendar_fetcher=calendar_fetch(items))
    run(make_ctx, uk(2026, 11, 23, 16, 20), sender, calendar_fetcher=calendar_fetch(items))
    assert sender.kinds == ["alert"]  # nothing else is due mid-afternoon, and the alert is not repeated


def test_rotation_is_remembered_between_runs(make_ctx, cfg):
    first, second = FakeSender(), FakeSender()
    run(make_ctx, uk(2026, 11, 23, 11, 0), first)  # Mon vip_am
    run(make_ctx, uk(2026, 11, 25, 11, 0), second)  # Wed vip_am
    state = State.load(cfg.root / "state" / "sent.json")
    assert state.last_rotation("funnel_vip")
    assert first.messages[0].text != second.messages[0].text


def test_preview_prints_every_message_type(make_ctx, capsys):
    result = run_preview(make_ctx(uk(2026, 11, 23, 8, 0), dry_run=True), ConsoleSender())
    out = capsys.readouterr().out
    for fragment in ("LONDON SESSION OPEN", "ASIAN SESSION OPEN", "NEW YORK SESSION OPEN", "OVERLAP", "Apply for mentorship", "VIP", "SAMPLE"):
        assert fragment in out
    assert "calendar" in result.skipped and "news" in result.skipped  # no network in tests: skipped, not crashed
    assert result.ok


def test_live_preview_sends_one_of_each_and_prints_a_summary(make_ctx, capsys):
    from rdfx_bot.runner import run_preview

    sender = FakeSender()
    ctx = make_ctx(uk(2026, 11, 23, 8, 0), dry_run=False)
    result = run_preview(ctx, sender, sleep=lambda s: None)
    assert {"asia", "london", "newyork", "overlap", "social"} <= set(sender.kinds)
    assert len(sender.kinds) == len(set(sender.kinds))  # one of each
    out = capsys.readouterr().out
    assert "SUMMARY" in out and "MISSING  news" in out  # no network in tests: said so, not silent
    assert "news" in result.skipped


def test_alert_wording_for_a_far_away_event():
    from datetime import timedelta

    from rdfx_bot.kinds.alerts import minutes_text

    class C:
        now = uk(2026, 11, 23, 3, 0)

    assert minutes_text(C, C.now + timedelta(minutes=315)) == "5 hours 15 minutes"
    assert minutes_text(C, C.now + timedelta(minutes=120)) == "2 hours"
    assert minutes_text(C, C.now + timedelta(minutes=15)) == "15 minutes"
