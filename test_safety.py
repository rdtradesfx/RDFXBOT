"""The 25 December hard block, and the date rules around it."""

from __future__ import annotations

from datetime import date

import pytest

from conftest import FakeSender, uk, utc
from rdfx_bot import cli
from rdfx_bot.models import Message
from rdfx_bot.runner import run_manual, run_scheduled
from rdfx_bot.safety import BlockedDateError, ensure_sendable, is_blocked
from rdfx_bot.scheduler import due_slots
from rdfx_bot.telegram import TelegramClient


def test_christmas_day_blocked_even_with_empty_config():
    assert is_blocked(date(2026, 12, 25), {"blocked_dates": []})
    assert is_blocked(date(2031, 12, 25), {})  # every year


def test_other_days_not_blocked_by_default():
    assert not is_blocked(date(2026, 12, 24), {"blocked_dates": ["12-25"]})
    assert not is_blocked(date(2026, 12, 26), {"blocked_dates": ["12-25"]})


def test_extra_blocked_dates_recurring_and_one_off():
    settings = {"blocked_dates": ["12-26", "2027-01-01", date(2027, 5, 3)]}
    assert is_blocked(date(2026, 12, 26), settings)
    assert is_blocked(date(2030, 12, 26), settings)  # MM-DD repeats yearly
    assert is_blocked(date(2027, 1, 1), settings)
    assert not is_blocked(date(2028, 1, 1), settings)  # full dates are one-off
    assert is_blocked(date(2027, 5, 3), settings)  # unquoted YAML date objects work


def test_telegram_client_refuses_on_christmas_and_never_calls_the_network():
    calls = []
    client = TelegramClient(
        "123456" + ":" + "Ab3" * 10, "-100123", {"blocked_dates": []},
        clock=lambda: uk(2026, 12, 25, 9, 0), post=lambda *a: calls.append(a) or (200, {"ok": True}),
    )
    with pytest.raises(BlockedDateError):
        client.send(Message(text="hello"))
    assert calls == []


def test_block_uses_the_uk_date_not_utc():
    ensure_sendable(utc(2026, 12, 24, 23, 59), {})  # still the 24th in the UK
    with pytest.raises(BlockedDateError):
        ensure_sendable(utc(2026, 12, 25, 23, 30), {})  # 25th in the UK
    with pytest.raises(BlockedDateError):
        ensure_sendable(utc(2026, 12, 25, 0, 5), {})


def test_manual_live_run_on_christmas_is_blocked(make_ctx):
    ctx = make_ctx(uk(2026, 12, 25, 10, 0))
    sender = FakeSender()
    result = run_manual(ctx, sender, "london")
    assert sender.messages == []
    assert result.failed == ["london"]


def test_scheduled_run_on_christmas_sends_nothing_even_if_slots_are_due(make_ctx):
    ctx = make_ctx(uk(2026, 12, 25, 8, 0))  # a Friday: london_open would normally be due
    sender = FakeSender()
    run_scheduled(ctx, sender)
    assert sender.messages == []


def test_scheduler_never_returns_slots_on_blocked_days(cfg):
    assert due_slots(uk(2026, 12, 25, 8, 0), cfg.schedule, cfg.settings, cfg.tz) == []
    settings = {"active_days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "blocked_dates": []}
    schedule = {"messages": {"late": {"kind": "london", "times": ["23:50"]}}}
    # A 23:50 slot from the 25th that is delayed past midnight must not go out on the 26th
    assert due_slots(uk(2026, 12, 26, 0, 10), schedule, settings, cfg.tz) == []


def test_there_is_no_force_flag():
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["run", "--force"])
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["send", "london", "--force"])
