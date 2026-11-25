"""Telegram client (secrets, retries, buttons), the state file, config checks and the command line."""

from __future__ import annotations

import json
import logging
import urllib.error
from datetime import timedelta

import pytest

from conftest import uk
from rdfx_bot import cli
from rdfx_bot.checks import check_config
from rdfx_bot.models import Button, Message
from rdfx_bot.state import State
from rdfx_bot.telegram import MAX_LEN, TelegramClient, TelegramError, redact, split_text

# Built at runtime (not one literal) so secret scanners never mistake this fake for a real token.
TOKEN = "123456789" + ":" + "Ab3" * 12
CHAT = "-1001234567890"
NOW = uk(2026, 11, 23, 9, 0)


def make_client(post, sleeps=None, settings=None):
    return TelegramClient(
        TOKEN, CHAT, settings or {}, clock=lambda: NOW, post=post,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
    )


# --------------------------------------------------------------------------- telegram
def test_message_is_sent_as_html_with_an_inline_url_button():
    calls = []

    def post(url, payload, timeout):
        calls.append((url, payload))
        return 200, {"ok": True, "result": {"message_id": 42}}

    msg = Message(text="<b>Hi</b>", buttons=[Button("JOIN NOW", "https://t.me/RDFX6"), Button("MORE", "https://example.com")])
    assert make_client(post).send(msg) == 42
    _url, payload = calls[0]
    assert payload["chat_id"] == CHAT and payload["parse_mode"] == "HTML"
    assert payload["link_preview_options"] == {"is_disabled": True}
    assert payload["reply_markup"]["inline_keyboard"] == [
        [{"text": "JOIN NOW", "url": "https://t.me/RDFX6"}],
        [{"text": "MORE", "url": "https://example.com"}],
    ]


def test_message_without_buttons_has_no_keyboard():
    seen = []
    make_client(lambda u, p, t: seen.append(p) or (200, {"ok": True})).send(Message(text="x"))
    assert "reply_markup" not in seen[0]


def test_rate_limit_is_retried_after_waiting():
    answers = iter([(429, {"ok": False, "parameters": {"retry_after": 3}}), (200, {"ok": True, "result": {"message_id": 1}})])
    sleeps = []
    assert make_client(lambda u, p, t: next(answers), sleeps).send(Message(text="x")) == 1
    assert sleeps == [3]


def test_server_errors_are_retried_then_given_up():
    attempts = []

    def post(url, payload, timeout):
        attempts.append(1)
        return 502, {"ok": False, "description": "Bad Gateway"}

    with pytest.raises(TelegramError):
        make_client(post).send(Message(text="x"))
    assert len(attempts) == 4


def test_formatting_rejection_falls_back_to_plain_text():
    payloads = []

    def post(url, payload, timeout):
        payloads.append(payload)
        if len(payloads) == 1:
            return 400, {"ok": False, "description": "Bad Request: can't parse entities: Unsupported start tag"}
        return 200, {"ok": True, "result": {"message_id": 9}}

    assert make_client(post).send(Message(text="<b>Bold</b> &amp; text")) == 9
    assert "parse_mode" not in payloads[1] and payloads[1]["text"] == "Bold & text"


def test_long_messages_are_split_and_the_button_goes_on_the_last_part():
    seen = []
    text = "\n\n".join(f"Block {i} " + "x" * 900 for i in range(10))
    make_client(lambda u, p, t: seen.append(p) or (200, {"ok": True})).send(Message(text=text, buttons=[Button("GO", "https://x.test")]))
    assert len(seen) > 1 and all(len(p["text"]) <= MAX_LEN for p in seen)
    assert ["reply_markup" in p for p in seen] == [False] * (len(seen) - 1) + [True]
    assert "".join(p["text"] for p in seen).replace("\n", "").count("Block") == 10


def test_split_text_leaves_short_text_alone_and_chops_one_giant_block():
    assert split_text("short") == ["short"]
    assert all(len(part) <= 100 for part in split_text("y" * 450, 100))


def test_errors_never_contain_the_token_or_chat_id():
    def refused(url, payload, timeout):
        return 401, {"ok": False, "description": f"Unauthorized for {TOKEN} chat {CHAT}"}

    with pytest.raises(TelegramError) as exc:
        make_client(refused).send(Message(text="x"))
    assert TOKEN not in str(exc.value) and CHAT not in str(exc.value)

    def network_down(url, payload, timeout):
        raise urllib.error.URLError(f"cannot reach https://api.telegram.org/bot{TOKEN}/sendMessage")

    with pytest.raises(TelegramError) as exc2:
        make_client(network_down).send(Message(text="x"))
    assert TOKEN not in str(exc2.value) and "bot123456789" not in str(exc2.value)
    assert exc2.value.__cause__ is None and exc2.value.__suppress_context__  # the URL cannot leak via the traceback


def test_redact_hides_known_secrets_and_anything_shaped_like_a_token():
    assert TOKEN not in redact(f"url https://api.telegram.org/bot{TOKEN}/x")
    assert redact("other 987654321" + ":" + "Zq" * 15 + " here") == "other *** here"
    assert CHAT not in redact(f"chat {CHAT}", (CHAT,))


def test_log_filter_scrubs_secrets_from_any_log_line(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    record = logging.LogRecord("x", logging.ERROR, "f", 1, "failed for %s in %s", (TOKEN, CHAT), None)
    cli._RedactFilter().filter(record)
    assert TOKEN not in record.getMessage() and CHAT not in record.getMessage()


def test_client_needs_both_secrets():
    with pytest.raises(TelegramError):
        TelegramClient("", CHAT)
    with pytest.raises(TelegramError):
        TelegramClient(TOKEN, "")


# --------------------------------------------------------------------------- state
def test_state_round_trip_and_dedupe(tmp_path):
    path = tmp_path / "state" / "sent.json"
    state = State.load(path)
    state.mark_sent("london_open@2026-11-23T08:00", NOW)
    state.mark_alerted("abc123", NOW)
    state.set_rotation("funnel_vip", "vip-next-step")
    state.save()
    again = State.load(path)
    assert again.has_sent("london_open@2026-11-23T08:00") and not again.has_sent("other")
    assert again.has_alerted("abc123")
    assert again.last_rotation("funnel_vip") == "vip-next-step" and again.last_rotation("social") is None
    assert not list(path.parent.glob(".state-*"))  # no temp files left behind


def test_corrupt_state_file_is_kept_aside_and_the_bot_starts_fresh(tmp_path):
    path = tmp_path / "sent.json"
    path.write_text("{not json", encoding="utf-8")
    state = State.load(path)
    assert state.sent == {} and (tmp_path / "sent.corrupt").exists()
    path.write_text("[1, 2]", encoding="utf-8")
    assert State.load(path).sent == {}


def test_old_entries_are_pruned_and_recent_ones_kept(tmp_path):
    state = State(tmp_path / "s.json")
    state.mark_sent("old", NOW - timedelta(days=20))
    state.mark_sent("recent", NOW - timedelta(days=2))
    state.mark_alerted("old-alert", NOW - timedelta(days=15))
    state.sent["broken"] = "not a date"
    state.prune(NOW, 14)
    assert list(state.sent) == ["recent"] and state.alerts == {}


def test_state_file_is_stable_and_readable_json(tmp_path):
    state = State(tmp_path / "s.json")
    state.mark_sent("b", NOW)
    state.mark_sent("a", NOW)
    state.save()
    data = json.loads((tmp_path / "s.json").read_text())
    assert list(data) == ["alerts", "notices", "rotation", "sent"] and list(data["sent"]) == ["a", "b"]


# --------------------------------------------------------------------------- config checks
def test_the_shipped_config_and_messages_pass_the_check(cfg):
    assert check_config(cfg) == []


def test_check_catches_common_phone_edit_mistakes(cfg):
    cfg.schedule["messages"]["asia_open"]["times"] = [780]  # unquoted 13:00 read as a number
    cfg.schedule["messages"]["daily_news"]["kind"] = "newz"
    cfg.schedule["messages"]["london_open"]["days"] = ["mon", "funday"]
    cfg.links["VIP_URL"] = "t.me/RDFX6"
    cfg.messages["sessions"]["london"]["text"] = "<b>Never closed"
    cfg.messages["funnels"]["vip"]["messages"][0]["buttons"] = [{"label": "X", "link": "NOPE_URL"}]
    cfg.messages["socials"]["messages"].append({"id": "instagram-keep-up", "text": "dupe"})
    problems = "\n".join(check_config(cfg))
    for fragment in ("put times in quotes", "unknown kind 'newz'", "unknown day 'funday'", "VIP_URL: must start with https://",
                     "never closed", "NOPE_URL", "duplicate id"):
        assert fragment in problems


# --------------------------------------------------------------------------- command line
@pytest.fixture
def offline(monkeypatch):
    def down(url, *a, **k):
        raise OSError("offline")

    monkeypatch.setattr("rdfx_bot.services.calendar_feed.http_get", down)
    monkeypatch.setattr("rdfx_bot.services.rss.http_get", down)


def test_cli_check_command(cfg, capsys):
    assert cli.main(["--root", str(cfg.root), "check"]) == 0
    assert "look good" in capsys.readouterr().out


def test_cli_dry_run_prints_what_is_due_and_sends_nothing(cfg, offline, capsys):
    assert cli.main(["--root", str(cfg.root), "run", "--dry-run", "--now", "2026-11-23T08:00"]) == 0
    out = capsys.readouterr().out
    assert "LONDON SESSION OPEN" in out and "DRY RUN" in out
    assert not (cfg.root / "state" / "sent.json").exists()


def test_cli_dry_run_on_christmas_day_prints_nothing(cfg, offline, capsys):
    assert cli.main(["--root", str(cfg.root), "run", "--dry-run", "--now", "2026-12-25T08:00"]) == 0
    assert "LONDON SESSION OPEN" not in capsys.readouterr().out


def test_cli_dry_run_at_weekend_prints_nothing(cfg, offline, capsys):
    assert cli.main(["--root", str(cfg.root), "run", "--dry-run", "--now", "2026-11-22T08:00"]) == 0  # a Sunday
    assert "SESSION OPEN" not in capsys.readouterr().out


def test_cli_preview_prints_every_message_type(cfg, offline, capsys):
    assert cli.main(["--root", str(cfg.root), "preview"]) == 0
    out = capsys.readouterr().out
    for fragment in ("ASIAN SESSION OPEN", "LONDON SESSION OPEN", "NEW YORK SESSION OPEN", "OVERLAP", "Apply for mentorship", "VIP", "NEWS ALERT"):
        assert fragment in out


def test_cli_now_flag_is_for_dry_runs_only(cfg, capsys):
    assert cli.main(["--root", str(cfg.root), "run", "--now", "2026-11-23T08:00"]) == 2


def test_cli_live_run_without_secrets_fails_clearly_and_sends_nothing(cfg, monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert cli.main(["--root", str(cfg.root), "run"]) == 2
    assert "SETUP ERROR" in capsys.readouterr().err


def test_cli_reports_a_broken_config_file_by_name(cfg, capsys):
    (cfg.root / "config" / "schedule.yaml").write_text("messages: [unclosed", encoding="utf-8")
    assert cli.main(["--root", str(cfg.root), "check"]) == 2
    assert "schedule.yaml" in capsys.readouterr().err
