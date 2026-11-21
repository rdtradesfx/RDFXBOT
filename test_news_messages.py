"""Daily news, session wording, funnel/social rotation, HTML escaping."""

from __future__ import annotations

import random
from datetime import timedelta

import pytest

from conftest import rss_xml, uk
from rdfx_bot.kinds import KINDS
from rdfx_bot.models import RetryLater
from rdfx_bot.rotation import pick
from rdfx_bot.services.rss import Headline, classify
from rdfx_bot.textutil import clean, esc, md_bold_to_html, render, safe_url, validate_html

NOW = uk(2026, 11, 23, 7, 0)  # Monday 07:00 UK
RECENT = NOW - timedelta(hours=2)


def fetcher(feeds: dict):
    """Return a fetch function serving XML by a word in the URL; any other feed 'is down'."""

    def fetch(url):
        for key, xml in feeds.items():
            if key in url:
                return xml
        raise OSError("feed down")

    return fetch


def build(make_ctx, kind, now=NOW, **kw):
    return KINDS[kind](make_ctx(now, **kw))


# --------------------------------------------------------------------------- daily news
def test_news_sorted_into_sections_with_source_names_and_links(make_ctx):
    xml = rss_xml(
        [
            ("Gold Price Forecast: XAU/USD climbs as safe haven demand rises", "https://www.fxstreet.com/news/gold-1", RECENT),
            ("Gold hits a record high", "https://www.fxstreet.com/news/gold-2", RECENT - timedelta(minutes=5)),
            ("Gold third story", "https://www.fxstreet.com/news/gold-3", RECENT - timedelta(minutes=10)),
            ("US Dollar Index slips ahead of Fed speakers", "https://www.fxstreet.com/news/usd-1", RECENT),
            ("Sterling rallies after UK inflation surprise", "https://www.fxstreet.com/news/gbp-1", RECENT),
        ]
    )
    message = build(make_ctx, "news", news_fetcher=fetcher({"fxstreet": xml}))
    text = message.text
    assert text.startswith("🚨RDFX | DAILY MARKET NEWS 🚨🗞️")
    assert "• 🇺🇸 USD: " in text and "• 🥇 GOLD: " in text and "• 🇬🇧 GBP: " in text
    assert '<a href="https://www.fxstreet.com/news/gold-1">' in text
    assert "(FXStreet)" in text
    assert "Gold third story" not in text  # max 2 per section
    assert text.count("Gold hits a record high") == 1
    assert validate_html(text) == []
    assert text.rstrip().endswith("Keep an eye on today's major economic releases and potential volatility.")


def test_news_never_copies_article_text(make_ctx):
    xml = rss_xml([("Sterling rallies", "https://www.fxstreet.com/news/gbp-1", RECENT)]).replace(
        b"</item>", b"<description>FULL ARTICLE BODY SHOULD NEVER APPEAR</description></item>"
    )
    message = build(make_ctx, "news", news_fetcher=fetcher({"fxstreet": xml}))
    assert "FULL ARTICLE BODY" not in message.text


def test_empty_sections_keep_the_friendly_default_lines(make_ctx):
    xml = rss_xml([("Sterling rallies after UK inflation surprise", "https://www.fxstreet.com/news/gbp-1", RECENT)])
    text = build(make_ctx, "news", news_fetcher=fetcher({"fxstreet": xml})).text
    assert "Latest developments affecting the dollar: nothing major so far, stay patient." in text
    assert "Latest developments affecting gold: nothing major so far, stay patient." in text
    assert "affecting sterling: nothing major" not in text  # that section has a real headline


def test_feeds_work_but_no_news_at_all_still_sends_a_complete_message(make_ctx):
    text = build(make_ctx, "news", news_fetcher=fetcher({"fxstreet": rss_xml([])})).text
    assert text.count("nothing major so far, stay patient.") == 3
    assert validate_html(text) == []


def test_all_feeds_down_means_retry_not_a_broken_message(make_ctx):
    with pytest.raises(RetryLater):
        build(make_ctx, "news")  # conftest network is always down


def test_headlines_older_than_24_hours_are_ignored(make_ctx):
    xml = rss_xml(
        [
            ("Gold is old news", "https://www.fxstreet.com/news/gold-old", NOW - timedelta(hours=30)),
            ("Gold is fresh", "https://www.fxstreet.com/news/gold-new", NOW - timedelta(hours=23)),
        ]
    )
    text = build(make_ctx, "news", news_fetcher=fetcher({"fxstreet": xml})).text
    assert "Gold is fresh" in text and "Gold is old news" not in text


def test_routine_admin_noise_is_excluded(make_ctx):
    xml = rss_xml([("Minutes of the Market Participants Group: sterling", "https://www.bankofengland.co.uk/m/1", RECENT)])
    text = build(make_ctx, "news", news_fetcher=fetcher({"bankofengland": xml})).text
    assert "Minutes of the" not in text


def test_bank_of_england_items_default_to_the_gbp_section(make_ctx):
    xml = rss_xml([("Governor speaks at conference", "https://www.bankofengland.co.uk/news/2026/x", RECENT)])
    text = build(make_ctx, "news", news_fetcher=fetcher({"bankofengland": xml})).text
    gbp_line = next(line for line in text.splitlines() if line.startswith("• 🇬🇧"))
    assert "Governor speaks at conference" in gbp_line


def test_headline_text_cannot_inject_markup_or_links(make_ctx):
    evil = 'Gold <script>alert(1)</script> & <a href="https://evil.example">click</a> "quotes"'
    xml = rss_xml([(evil, "https://www.fxstreet.com/news/gold-1", RECENT)])
    text = build(make_ctx, "news", news_fetcher=fetcher({"fxstreet": xml})).text
    assert "<script" not in text and "evil.example" not in text
    assert "&amp;" in text
    assert validate_html(text) == []


def test_links_to_other_sites_or_unsafe_schemes_are_dropped(make_ctx):
    xml = rss_xml(
        [
            ("Gold: off-site link", "https://evil.example/gold", RECENT),
            ("Gold: script link", "javascript:alert(1)", RECENT),
            ("Gold: plain http link", "http://www.fxstreet.com/news/gold-http", RECENT),
            ("Gold: quote in link", 'https://www.fxstreet.com/news/"onmouseover="x', RECENT),
            ("Gold: the good one", "https://www.fxstreet.com/news/ok", RECENT),
        ]
    )
    text = build(make_ctx, "news", news_fetcher=fetcher({"fxstreet": xml})).text
    assert "the good one" in text
    for bad in ("off-site", "script link", "plain http", "quote in link"):
        assert bad not in text


def test_fed_keyword_is_case_sensitive_so_fed_up_does_not_match():
    rules = {"usd": {"keywords": [], "keywords_exact": ["Fed"]}}
    when = uk(2026, 11, 23, 6)
    assert classify(Headline("Fed holds rates", "https://x.test/1", "S", when), rules) == "usd"
    assert classify(Headline("Savers are fed up with banks", "https://x.test/2", "S", when), rules) is None


def test_headline_picks_the_best_matching_section_only_once(make_ctx):
    xml = rss_xml([("Gold slips as US Dollar and Treasury yields rise", "https://www.fxstreet.com/news/mix", RECENT)])
    text = build(make_ctx, "news", news_fetcher=fetcher({"fxstreet": xml})).text
    assert text.count("Gold slips as US Dollar") == 1


# --------------------------------------------------------------------------- session wording
def test_session_messages_use_the_exact_wording_and_html(make_ctx):
    london = build(make_ctx, "london").text
    assert london.startswith("<b>RDFX: LONDON SESSION OPEN</b>")
    assert "The London session is now LIVE. 🇬🇧" in london
    assert "Stay patient, wait for confirmation and don't force trades." in london
    assert london.rstrip().endswith("<b>Precision Meets Profit.</b> 🥇")

    ny = build(make_ctx, "newyork").text
    assert ny.startswith("RDFX: NEW YORK SESSION OPEN🇺🇸🗽")
    assert "US liquidity is entering the market. Expect potential volatility across USD pairs and Gold." in ny
    assert ny.rstrip().endswith("<b>RDFX | Precision Meets Profit</b>")

    overlap = build(make_ctx, "overlap").text
    assert overlap.startswith("🔥 <b>RDFX: LONDON x NEW YORK OVERLAP</b>")
    assert "London 🇬🇧 + New York 🇺🇸 are both LIVE." in overlap

    asia = build(make_ctx, "asia").text
    assert asia.startswith("RDFX: ASIAN SESSION OPEN🌎")
    assert "Stay disciplined. 🫡" in asia
    assert asia.rstrip().endswith("RDFX | Precision Meets Profit! 🥇")
    for text in (london, ny, overlap, asia):
        assert validate_html(text) == []


def test_the_precicion_typo_is_nowhere_in_the_messages(cfg):
    import json

    blob = json.dumps(cfg.messages, ensure_ascii=False)
    assert "Precicion" not in blob and "Precision Meets Profit" in blob


# --------------------------------------------------------------------------- funnels
def test_funnel_buttons_use_the_links_file(make_ctx, cfg):
    vip = build(make_ctx, "funnel_vip")
    assert [(b.label, b.url) for b in vip.buttons] == [("JOIN NOW", "https://t.me/RDFX6")]
    mentor = build(make_ctx, "funnel_mentorship")
    assert [(b.label, b.url) for b in mentor.buttons] == [("APPLY NOW", "https://tally.so/r/wdBLED")]
    cfg.links["VIP_URL"] = "https://t.me/changed"
    assert build(make_ctx, "funnel_vip").buttons[0].url == "https://t.me/changed"


def test_funnel_text_has_no_pasted_link(make_ctx):
    for _ in range(10):
        for kind in ("funnel_vip", "funnel_mentorship", "social"):
            assert "http" not in build(make_ctx, kind, seed=_).text


@pytest.mark.parametrize("kind,pool_size", [("funnel_vip", 6), ("funnel_mentorship", 2)])
def test_funnel_rotation_never_repeats_immediately_and_uses_every_message(make_ctx, kind, pool_size):
    ctx = make_ctx(NOW, seed=7)
    seen, previous = [], None
    for _ in range(300):
        message = KINDS[kind](ctx)
        pool, message_id = message.rotation
        assert message_id != previous
        ctx.state.set_rotation(pool, message_id)
        previous = message_id
        seen.append(message_id)
    assert len(set(seen)) == pool_size


def test_rotation_with_a_single_choice_still_works():
    assert pick(["only"], "only", random.Random(1)) == "only"
    with pytest.raises(ValueError):
        pick([], None, random.Random(1))


def test_rotation_is_not_a_fixed_cycle():
    rng = random.Random(3)
    ids = ["a", "b", "c", "d"]
    last, sequence = None, []
    for _ in range(60):
        last = pick(ids, last, rng)
        sequence.append(last)
    assert sequence[:4] != ids and len(set(sequence)) == 4


# --------------------------------------------------------------------------- socials
def test_tiktok_message_and_button_are_left_out_while_the_link_is_empty(make_ctx, cfg):
    assert cfg.links["TIKTOK_URL"] == ""
    ctx = make_ctx(NOW, seed=11)
    seen_ids = set()
    for _ in range(200):
        message = KINDS["social"](ctx)
        ctx.state.set_rotation(*message.rotation)
        seen_ids.add(message.rotation[1])
        assert "tiktok" not in message.text.lower()
        assert all("tiktok.com" not in b.url and b.label != "TIKTOK" for b in message.buttons)
    assert "tiktok-more-content" not in seen_ids
    assert seen_ids == {"instagram-keep-up", "instagram-new-content", "all-platforms", "youtube-watch-and-learn"}


def test_all_platforms_message_gets_instagram_and_youtube_buttons_only_without_tiktok(make_ctx, cfg):
    ctx = make_ctx(NOW)
    pool = cfg.messages["socials"]
    from rdfx_bot.kinds._pool import eligible_messages

    buttons = {e["id"]: [b.label for b in bs] for e, bs in eligible_messages(pool, ctx)}
    assert buttons["all-platforms"] == ["INSTAGRAM", "YOUTUBE"]


def test_tiktok_link_switches_on_the_tiktok_message_and_button(make_ctx, cfg):
    cfg.links["TIKTOK_URL"] = "https://www.tiktok.com/@rdfx"
    from rdfx_bot.kinds._pool import eligible_messages

    buttons = {e["id"]: [b.label for b in bs] for e, bs in eligible_messages(cfg.messages["socials"], make_ctx(NOW))}
    assert buttons["tiktok-more-content"] == ["FOLLOW ON TIKTOK"]
    assert buttons["all-platforms"] == ["INSTAGRAM", "YOUTUBE", "TIKTOK"]


def test_invalid_link_is_treated_as_empty_not_an_error(make_ctx, cfg):
    cfg.links["INSTAGRAM_URL"] = "javascript:alert(1)"
    cfg.links["YOUTUBE_URL"] = ""
    assert KINDS["social"](make_ctx(NOW)) is None  # nothing sendable: skipped quietly


# --------------------------------------------------------------------------- text helpers
def test_esc_neutralises_markup():
    assert esc("<b>x</b> & y") == "&lt;b&gt;x&lt;/b&gt; &amp; y"


def test_clean_strips_tags_controls_and_truncates():
    assert clean("<i>Hi</i>\x00‮  there\n\tfriend") == "Hi there friend"
    assert len(clean("x" * 500, 50)) == 50


def test_safe_url_rules():
    assert safe_url("https://www.fxstreet.com/a", ["fxstreet.com"])
    assert safe_url("https://evilfxstreet.com/a", ["fxstreet.com"]) is None
    assert safe_url("https://fxstreet.com.evil.example/a", ["fxstreet.com"]) is None
    assert safe_url("http://www.fxstreet.com/a") is None
    assert safe_url("https://x.test/a b") is None


def test_render_converts_bold_and_leaves_inserted_values_alone():
    assert md_bold_to_html("**Hi** there") == "<b>Hi</b> there"
    assert render("**Hi** {name}", name="**not bold** <i>") == "<b>Hi</b> **not bold** <i>"
    assert render("keep {unknown} as is") == "keep {unknown} as is"


def test_validate_html_catches_what_telegram_would_reject():
    assert validate_html("<b>ok</b> &amp; fine") == []
    assert validate_html("<b>never closed")
    assert validate_html("a < b")
    assert validate_html("fish & chips")
    assert validate_html("<script>x</script>")
