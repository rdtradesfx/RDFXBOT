"""Plan-B messages when feeds are down, and news that stays relevant to each pair."""

from __future__ import annotations

from datetime import timedelta

from conftest import FakeSender, calendar_fetch, ff, no_network, rss_xml, uk
from rdfx_bot.kinds import KINDS
from rdfx_bot.runner import run_scheduled
from rdfx_bot.textutil import validate_html


def run(make_ctx, now, sender, **kw):
    return run_scheduled(make_ctx(now, **kw), sender, sleep=lambda s: None)


def only(sender, kind):
    return [m for m in sender.messages if m.kind == kind]


def fetch_by_name(feeds):
    def fetch(url):
        for key, xml in feeds.items():
            if key in url:
                return xml
        raise OSError("feed down")

    return fetch


# --------------------------------------------------------------------------- calendar plan B
def test_calendar_feed_down_waits_then_sends_a_plan_b_message_once(make_ctx, cfg):
    sender = FakeSender()
    # Scheduled 08:30, window closes 09:15, plan B only in the last 15 minutes (from 09:00).
    for minute in (30, 35, 40, 45, 50, 55):
        run(make_ctx, uk(2026, 11, 23, 8, minute), sender)
    assert only(sender, "calendar") == []  # still hoping the feed comes back
    run(make_ctx, uk(2026, 11, 23, 9, 0), sender)
    assert len(only(sender, "calendar")) == 1
    message = only(sender, "calendar")[0]
    assert "could not be loaded" in message.text and "ECONOMIC CALENDAR" in message.text
    assert [(b.label, b.url) for b in message.buttons] == [("OPEN CALENDAR", "https://www.forexfactory.com/calendar")]
    assert validate_html(message.text) == []
    run(make_ctx, uk(2026, 11, 23, 9, 5), sender)
    run(make_ctx, uk(2026, 11, 23, 9, 10), sender)
    assert len(only(sender, "calendar")) == 1  # never twice, never after the window


def test_calendar_comes_back_in_time_so_the_real_message_goes_instead(make_ctx):
    sender = FakeSender()
    run(make_ctx, uk(2026, 11, 23, 8, 30), sender)  # feed down
    items = [ff("CPI y/y", "GBP", "2026-11-23T04:00:00-05:00", "High", "3.8%", "3.6%")]
    run(make_ctx, uk(2026, 11, 23, 8, 50), sender, calendar_fetcher=calendar_fetch(items))
    cal = only(sender, "calendar")
    assert len(cal) == 1 and "CPI y/y" in cal[0].text and "could not be loaded" not in cal[0].text


def test_calendar_plan_b_button_link_can_be_changed_in_links_yaml(make_ctx, cfg):
    cfg.links["CALENDAR_URL"] = "https://example.com/calendar"
    sender = FakeSender()
    run(make_ctx, uk(2026, 11, 23, 9, 5), sender)
    assert only(sender, "calendar")[0].buttons[0].url == "https://example.com/calendar"


def test_plan_b_can_be_switched_off(make_ctx, cfg):
    cfg.schedule["fallback_minutes"] = 0
    sender = FakeSender()
    run(make_ctx, uk(2026, 11, 23, 9, 5), sender)
    assert only(sender, "calendar") == []


def test_plan_b_wording_comes_from_extras_yaml(make_ctx, cfg):
    cfg.messages["extras"]["calendar"]["fallback"] = "📅 My own wording"
    cfg.messages["extras"]["calendar"]["fallback_button"] = "GO"
    sender = FakeSender()
    run(make_ctx, uk(2026, 11, 23, 9, 5), sender)
    cal = only(sender, "calendar")[0]
    assert cal.text == "📅 My own wording" and cal.buttons[0].label == "GO"


def test_missing_extras_file_falls_back_to_built_in_wording(make_ctx, cfg):
    cfg.messages["extras"] = {}
    sender = FakeSender()
    run(make_ctx, uk(2026, 11, 23, 9, 5), sender)
    assert "could not be loaded" in only(sender, "calendar")[0].text


# --------------------------------------------------------------------------- news plan B
def test_news_feeds_all_down_sends_a_plan_b_message_late_in_the_window(make_ctx):
    sender = FakeSender()
    run(make_ctx, uk(2026, 11, 23, 7, 0), sender)
    run(make_ctx, uk(2026, 11, 23, 7, 20), sender)
    assert "news" not in sender.kinds
    run(make_ctx, uk(2026, 11, 23, 7, 30), sender)
    assert sender.kinds.count("news") == 1
    text = next(m.text for m in sender.messages if m.kind == "news")
    assert "feeds are unavailable" in text and "nothing major" not in text  # honest, not a fake "quiet day"
    run(make_ctx, uk(2026, 11, 23, 7, 40), sender)
    assert sender.kinds.count("news") == 1


def test_news_with_one_working_feed_is_a_normal_briefing_not_plan_b(make_ctx):
    when = uk(2026, 11, 23, 5, 0)
    xml = rss_xml([("Gold climbs as safe haven demand rises", "https://www.fxstreet.com/news/g", when)])
    sender = FakeSender()
    run(make_ctx, uk(2026, 11, 23, 7, 0), sender, news_fetcher=fetch_by_name({"fxstreet": xml}))
    text = next(m.text for m in sender.messages if m.kind == "news")
    assert "Gold climbs as safe haven demand rises" in text and "unavailable" not in text


# --------------------------------------------------------------------------- relevance
NOW = uk(2026, 11, 23, 7, 0)
EARLIER = NOW - timedelta(hours=3)
EVENTS = [
    ff("CPI y/y", "GBP", "2026-11-23T04:00:00-05:00", "High", "3.8%", "3.6%"),          # 09:00 UK
    ff("Flash Manufacturing PMI", "GBP", "2026-11-23T04:30:00-05:00", "Medium"),         # 09:30 UK
    ff("Core PCE Price Index m/m", "USD", "2026-11-23T08:30:00-05:00", "High", "0.3%"),  # 13:30 UK
    ff("FOMC Member Waller Speaks", "USD", "2026-11-23T12:00:00-05:00", "Medium"),       # 17:00 UK
    ff("Eurozone CPI", "EUR", "2026-11-23T05:00:00-05:00", "High"),                      # EUR: not in any section
]


def news(make_ctx, items, events=EVENTS):
    feeds = {"fxstreet": rss_xml(items)}
    ctx = make_ctx(NOW, news_fetcher=fetch_by_name(feeds), calendar_fetcher=calendar_fetch(events), dry_run=True)
    return KINDS["news"](ctx).text


def section(text, title):
    """All the bullet lines for one market, e.g. '🇺🇸'."""
    return "\n".join(line for line in text.split("\n") if line.startswith(f"• {title}"))


HEADLINES = [
    ("Gold edges higher as safe-haven demand returns", "https://www.fxstreet.com/news/1", EARLIER),
    ("Sterling slips after UK inflation data", "https://www.fxstreet.com/news/2", EARLIER),
    ("US Dollar Index firms ahead of Fed minutes", "https://www.fxstreet.com/news/3", EARLIER),
    ("Eurozone economy stalls in November", "https://www.fxstreet.com/news/4", EARLIER),
]


def test_each_section_only_talks_about_its_own_market(make_ctx):
    text = news(make_ctx, HEADLINES)
    gold, usd, eur, gbp = (section(text, x) for x in ("🥇", "🇺🇸", "🇪🇺", "🇬🇧"))
    assert "Gold edges" in gold and "Dollar" not in gold
    assert "US Dollar Index" in usd and "Gold edges" not in usd and "Sterling" not in usd
    assert "Eurozone economy stalls" in eur and "Sterling" not in eur
    assert "Sterling slips" in gbp and "Gold" not in gbp
    assert text.index("• 🇺🇸") < text.index("• 🥇") < text.index("• 🇪🇺") < text.index("• 🇬🇧")


def test_war_headlines_show_under_gold_and_usd(make_ctx):
    text = news(make_ctx, [("Missile strikes raise fears of wider war in the Middle East", "https://www.fxstreet.com/news/9", EARLIER)])
    assert "Missile strikes" in section(text, "🥇") and "Missile strikes" in section(text, "🇺🇸")
    assert "Missile strikes" not in section(text, "🇬🇧")


def test_every_market_always_has_a_line_and_headlines_are_bold(make_ctx):
    text = news(make_ctx, [HEADLINES[0]], events=[])
    for flag in ("🇺🇸", "🥇", "🇪🇺", "🇬🇧", "🇦🇺"):
        assert f"• {flag}" in text
    assert "<b>Gold edges higher as safe-haven demand returns (FXStreet)</b>" in text or "<b>Gold edges higher" in text
    assert "Latest developments affecting the dollar: nothing major so far, stay patient." in section(text, "🇺🇸")
    assert "{sections}" not in text and validate_html(text) == []


def test_no_headlines_at_all_says_nothing_major_for_each_market(make_ctx):
    text = news(make_ctx, [], events=[])
    assert text.count("nothing major so far, stay patient") == 5 and validate_html(text) == []


def test_news_still_works_when_the_calendar_is_down(make_ctx):
    items = [("Gold edges higher as safe-haven demand returns", "https://www.fxstreet.com/news/1", EARLIER)]
    ctx = make_ctx(NOW, news_fetcher=fetch_by_name({"fxstreet": rss_xml(items)}), calendar_fetcher=no_network, dry_run=True)
    text = KINDS["news"](ctx).text
    assert "Gold edges higher" in text and "Watch today" not in text and validate_html(text) == []


def test_fed_admin_releases_are_not_treated_as_dollar_news(make_ctx):
    items = [
        ("Federal Reserve Board announces approval of application by a bank", "https://www.fxstreet.com/news/a", EARLIER),
        ("Fed's Powell says inflation progress is uneven", "https://www.fxstreet.com/news/b", EARLIER),
    ]
    text = news(make_ctx, items, events=[])
    assert "approval of application" not in text and "Powell says inflation" in text
