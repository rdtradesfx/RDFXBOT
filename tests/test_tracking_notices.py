"""Tracked links on funnel/social buttons, and the private failure notices."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from conftest import FakeSender, uk
from rdfx_bot.inbox import admin_id, notify_run_problems, process_inbox
from rdfx_bot.runner import RunResult, run_manual
from rdfx_bot.telegram import TelegramClient
from rdfx_bot.tracking import ref_code, track_url

S = {}


def q(url):
    return parse_qs(urlparse(url).query)


def test_tally_link_gets_the_tag_in_a_hidden_field_and_utm():
    url = track_url("https://tally.so/r/wdBLED", "mentorship-process", "funnel", S)
    assert url.startswith("https://tally.so/r/wdBLED?")
    assert q(url) == {"utm_source": ["telegram"], "utm_medium": ["funnel"], "utm_campaign": ["mentorship-process"], "source": ["mentorship-process"]}


def test_vip_chat_link_opens_with_the_tag_in_the_typed_message():
    url = track_url("https://t.me/RDFX6", "vip-next-step", "funnel", S, ref="V-7K2")
    assert urlparse(url).path == "/RDFX6"
    assert q(url)["text"] == ["Hi Ryan, I'd like to join RDFX VIP. Ref: V-7K2"]  # short code, not the message id


def test_other_links_get_utm_and_existing_params_are_kept():
    url = track_url("https://www.instagram.com/ryan_drewery6/?hl=en", "instagram-keep-up", "social", S)
    assert q(url)["hl"] == ["en"] and q(url)["utm_campaign"] == ["instagram-keep-up"] and q(url)["utm_medium"] == ["social"]


def test_tracking_can_be_switched_off_and_odd_links_are_left_alone():
    assert track_url("https://tally.so/r/x", "t", "funnel", {"tracking": {"enabled": False}}) == "https://tally.so/r/x"
    assert track_url("http://insecure.example/x", "t", "funnel", S) == "http://insecure.example/x"
    assert track_url("https://t.me/somechannel/123", "t", "funnel", S) == "https://t.me/somechannel/123"
    assert track_url("https://t.me/RDFX6?text=hello", "t", "funnel", S) == "https://t.me/RDFX6?text=hello"


def test_chat_text_is_editable():
    s = {"tracking": {"chat_text": "VIP please {ref} {tag}"}}
    assert q(track_url("https://t.me/RDFX6", "abc", "funnel", s, ref="V-1"))["text"] == ["VIP please V-1 abc"]


def test_every_funnel_and_social_message_sends_its_own_tag(make_ctx, cfg):
    cfg.links["TIKTOK_URL"] = "https://www.tiktok.com/@rdfx"
    seen = {}
    for kind in ("funnel_mentorship", "funnel_vip", "social"):
        for seed in range(12):
            sender = FakeSender()
            run_manual(make_ctx(uk(2026, 11, 23, 11, 0), seed=seed), sender, kind)
            message = sender.messages[0]
            tag = message.rotation[1]
            for button in message.buttons:
                params = q(button.url)
                assert tag in (params.get("utm_campaign") or [""])[0] or ref_code("V", tag) in params.get("text", [""])[0]
            seen[tag] = message.buttons
    assert {"vip-next-step", "mentorship-process", "instagram-keep-up"} <= set(seen)


class FakeClient:
    def __init__(self, updates=()):
        self.updates = list(updates)
        self.private = []
        self.acked = []

    def get_updates(self, offset=None, limit=100):
        if offset is not None:
            self.acked.append(offset)
            return []
        return list(self.updates)

    def send_private(self, chat_id, text):
        self.private.append((str(chat_id), text))
        return True


def test_myid_replies_with_only_the_askers_own_id_and_everything_else_is_ignored(make_ctx):
    updates = [
        {"update_id": 1, "message": {"text": "/myid", "from": {"id": 999}, "chat": {"id": 999, "type": "private"}}},
        {"update_id": 2, "message": {"text": "BUY EURUSD 1.08 SL 1.07 TP 1.10", "from": {"id": 999}, "chat": {"id": 999, "type": "private"}}},
        {"update_id": 3, "message": {"text": "/myid", "from": {"id": 5}, "chat": {"id": -100, "type": "group"}}},
    ]
    client = FakeClient(updates)
    assert process_inbox(make_ctx(uk(2026, 11, 23, 10, 0)), client) == 1
    assert len(client.private) == 1 and client.private[0][0] == "999" and "999" in client.private[0][1]
    assert client.acked == [2, 3, 4]


def test_admin_id_comes_from_the_secret_or_settings(cfg, monkeypatch):
    monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_ID", raising=False)
    assert admin_id(cfg) == ""
    cfg.settings["admin_chat_id"] = 4242
    assert admin_id(cfg) == "4242"
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "777")
    assert admin_id(cfg) == "777"


def test_failure_notice_is_sent_once_a_day(make_ctx, cfg, monkeypatch):
    monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_ID", raising=False)
    cfg.settings["admin_chat_id"] = "4242"
    ctx = make_ctx(uk(2026, 11, 23, 10, 0))
    client = FakeClient()
    result = RunResult(failed=["london_open"], warnings=["'daily_news' data was unavailable"])
    notify_run_problems(ctx, client, result)
    notify_run_problems(ctx, client, result)  # the next 5-minute run: no repeat
    assert len(client.private) == 2 and "london_open" in client.private[0][1]
    assert all(chat == "4242" for chat, _ in client.private)


def test_no_notice_without_an_owner_or_when_switched_off(make_ctx, cfg, monkeypatch):
    monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_ID", raising=False)
    client = FakeClient()
    notify_run_problems(make_ctx(uk(2026, 11, 23, 10, 0)), client, RunResult(failed=["x"]))
    assert client.private == []
    cfg.settings["admin_chat_id"] = "4242"
    cfg.settings["failure_notices"] = False
    notify_run_problems(make_ctx(uk(2026, 11, 23, 10, 0)), client, RunResult(failed=["x"]))
    assert client.private == []


def test_telegram_client_reads_and_acknowledges_updates():
    calls = []

    def post(url, payload, timeout):
        calls.append((url.rsplit("/", 1)[1], payload))
        if url.endswith("getUpdates"):
            return 200, {"ok": True, "result": [{"update_id": 5}]}
        return 200, {"ok": True, "result": {"message_id": 1}}

    client = TelegramClient("123456:" + "A" * 30, "-100", {}, post=post)
    assert client.get_updates() == [{"update_id": 5}]
    client.get_updates(offset=6, limit=1)
    assert calls[1][1]["offset"] == 6 and calls[0][0] == "getUpdates"
    assert client.send_private("4242", "hi") is True


def test_ref_codes_are_short_stable_and_unique_across_every_message(cfg):
    assert ref_code("V", "vip-next-step") == ref_code("V", "vip-next-step")
    codes = {}
    for pool, prefix in (("funnels.vip", "V"), ("funnels.mentorship", "M"), ("socials", "S")):
        data = cfg.messages["funnels"][pool.split(".")[1]] if "." in pool else cfg.messages["socials"]
        for entry in data["messages"]:
            code = ref_code(prefix, entry["id"])
            assert code not in codes, f"{code} used twice"
            codes[code] = entry["id"]
            assert len(code) == 5
