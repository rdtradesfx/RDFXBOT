# RDFX Telegram Bot

**Precision Meets Profit.** Posts scheduled RDFX messages into your Telegram channel or group: session opens, daily market news, the economic calendar, news alerts 15 minutes before big events, VIP / mentorship funnel posts and social reminders.

- Runs entirely on **GitHub Actions**. No server, no paid services, no API keys except the Telegram bot token.
- Every word of every message lives in plain text files you can edit from your phone in the GitHub web editor.
- All times are **UK time** and GMT/BST is automatic.
- **Never sends on 25 December**, and nothing (schedule, manual run, setting) can override that.

---

## 1. What it sends and when (UK time, Monday to Friday)

| Time | Message |
|---|---|
| 00:00 | Asian session open |
| 07:00 | Daily market news (USD / GOLD / GBP headlines) |
| 08:00 | London session open |
| 08:30 | Economic calendar for today |
| 11:00 | Mon/Wed/Fri: 1-1 mentorship funnel. Tue/Thu: VIP funnel |
| 12:00 | Social follow reminder |
| 13:00 | New York session open |
| 13:03 | London x New York overlap (3 minute stagger, set `offset_minutes: 0` to send together) |
| 15 min before each High/Medium event | News alert |
| 18:00 | VIP funnel |
| 20:00 | Social follow reminder |

Weekends: nothing is sent. All of this is in `config/schedule.yaml`.

---

## 2. Why a public repo (the free-tier check)

I checked [GitHub's billing docs](https://docs.github.com/en/billing/concepts/product-billing/github-actions):

- Standard GitHub-hosted runners are **free in public repositories**.
- A **private** repo on the Free plan only gets **$12 of included compute a month** (roughly 2,000 Linux minutes at GitHub's current rate). A bot that wakes up every 5 minutes is about 8,600 runs a month, so a private repo would run out of free minutes part-way through the month.

So: **make the repo public.** That is safe here because:

- Your bot token and chat ID live in **GitHub Secrets**, which are never shown in a public repo, never in the code and never in the logs.
- What the public *can* see is what is already public anyway: the message wording, your public links and the schedule.
- Nobody else can send messages or change anything. Only people you add as collaborators can edit the repo or run workflows. Secrets are not passed to forks.

If you ever need it private, switch to a paid plan or reduce how often it runs; the bot logic stays the same.

---

## 3. Setup (about 15 minutes, no coding)

### Step 1: Create the bot
1. In Telegram, open **@BotFather** and send `/newbot`.
2. Pick a name and a username ending in `bot`.
3. BotFather replies with a **token** that looks like `123456789:AAH...`. Copy it. **Treat it like a password.** Never post it anywhere.

### Step 2: Add the bot to your channel or group
- **Channel:** Channel settings > Administrators > Add Administrator > pick your bot > allow **Post Messages**.
- **Group:** add the bot as a member (make it an admin if the group restricts messages).

### Step 3: Get the chat ID
Easiest option for a **public channel**: the chat ID is just its @username, e.g. `@rdfxchannel`.

For a private channel or group:
1. Post any message in the channel/group.
2. In your browser open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` (replace `<YOUR_TOKEN>` with your token, keep the word `bot` before it).
3. Find `"chat":{"id":-100...` and copy that number (it starts with `-`). Do not share this page.

### Step 4: Create the GitHub repo
1. On GitHub: **New repository**, name it e.g. `rdfx-telegram-bot`, choose **Public**.
2. Upload all the files from this folder (**Add file > Upload files**; drag the whole folder contents in, including the hidden `.github` folder), then commit to `main`.
   If dragging the `.github` folder is awkward on your device, use **Add file > Create new file** and type `.github/workflows/bot.yml` as the name to create it in place.

### Step 5: Add the two secrets
Repo **Settings > Secrets and variables > Actions > New repository secret**:

| Name (exactly) | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token from BotFather |
| `TELEGRAM_CHAT_ID` | the chat ID or @username |

### Step 6: First dry run (sends nothing)
1. Repo **Actions** tab > **RDFX bot** (left side) > **Run workflow**.
2. Choose `preview`, leave **Dry run** ticked, press **Run workflow**.
3. Open the run, open the **Run the bot** step. Every message type is printed there so you can read it.

### Step 7: Send one real test message
Run workflow again with `london` selected and **Dry run un-ticked**. The London message should appear in your channel. If it does, you are done.

### Step 8: Go live
Nothing else to do. The schedule starts by itself. Within the hour you will see a run every ~5 minutes under **Actions** (most do nothing and finish in seconds, which is normal).

> **Before going live, check these two things**
> 1. `config/links.yaml`: `INSTAGRAM_URL` currently points at `ryan_drewery6` as you specified. Make sure that is the account you want in the buttons.
> 2. `messages/socials.yaml`: the YouTube message (`youtube-watch-and-learn`) was written by me, not you. Approve or reword it.

---

## 4. Everyday changes (all doable from your phone)

Open a file on GitHub, tap the pencil, edit, **Commit changes**. The next run uses it. The bot checks your files on every run and the log will show a yellow warning if you made a typo.

| I want to... | Edit this |
|---|---|
| Change the wording of a session message | `messages/sessions.yaml` |
| Change / add / remove VIP or mentorship posts | `messages/funnels.yaml` (copy a block, give it a new unique `id`) |
| Change / add / remove social reminders | `messages/socials.yaml` |
| Change the news, calendar or alert layout | `messages/templates.yaml` (keep the `{curly_words}` exactly as written) |
| Change **any link** | `config/links.yaml` (one place, every message and button updates) |
| Add the TikTok link | `config/links.yaml` > `TIKTOK_URL`. The TikTok message and button switch on automatically |
| Change a time or day | `config/schedule.yaml` (always keep times in quotes, e.g. `"13:00"`) |
| Switch one message type off | `config/schedule.yaml` > set `enabled: false` on it |
| Switch news alerts off | `config/schedule.yaml` > `alerts:` > `enabled: false` |
| **Pause the whole bot** | `config/settings.yaml` > `enabled: false` (set back to `true` to resume) |
| Add a blocked date | `config/settings.yaml` > `blocked_dates`, e.g. `"12-26"` (every year) or `"2027-01-01"` (once) |
| Add a news event the feed missed | `events.json` (see below) |
| Change which currencies are included | `config/sources.yaml` > `calendar` > `currencies` |
| Change the news sources or keywords | `config/sources.yaml` > `news` |
| Stack the overlap on top of New York | `config/schedule.yaml` > `overlap` > `offset_minutes: 0` |

**Formatting in messages:** `**bold**` works. Write `&amp;` for `&`. Don't type a stray `<` or `>`.

**Adding a manual event** (`events.json`; times are UK time):
```json
[
  {"title": "Bank of England Governor Speaks", "currency": "GBP", "impact": "High",
   "datetime": "2026-11-26T14:30", "forecast": "", "previous": ""}
]
```
`impact` is `High` or `Medium`. Manual events get alerts like any other. If the live feed is down and only manual events exist, the 08:30 calendar waits and retries instead of falsely saying "nothing today".

### 25 December and blocked dates
25 December is blocked **inside the program** (`src/rdfx_bot/safety.py`), checked against the UK date, and again at the moment of sending. There is no `--force` option. Removing `"12-25"` from `settings.yaml` does not unblock it. Add other days (26 Dec, 1 Jan) to `blocked_dates`.

---

## 5. How it works and what to expect (honest notes)

- **Timing can drift.** GitHub's `*/5` schedule is best-effort. Runs can start a few minutes late, and occasionally much later when GitHub is busy. The bot tolerates this: a message is still sent if it is within its **catch-up window** (default 45 minutes, `catch_up_minutes` in `schedule.yaml`). After that it is skipped, so a session message never lands hours late.
- **News alerts are "15 minutes or less".** An alert goes out on the first run when an event is 15 minutes or fewer away. If a run is late, the alert says the real time left (e.g. "Releasing in 9 minutes"). It never alerts for something already released, and sends once per event.
- **Nothing is sent twice.** `state/sent.json` records every send and is committed back to the repo after each run. Runs never overlap (a concurrency lock).
- **The calendar feed is unofficial.** It is the free ForexFactory weekly JSON (`nfs.faireconomy.media`). It was **not reachable from the environment I built this in**, so it has been tested against the known field layout and a lot of fake data, but not live. Your first `preview` run will tell you immediately: a working feed prints a calendar; a failing one logs "feed unavailable". If it ever disappears, the bot keeps using the last good copy for 48 hours, then skips calendar messages rather than sending wrong ones. The feed is fetched at most once an hour.
- **News sources.** The BoE, FXStreet and Federal Reserve speeches feeds were confirmed working; the Fed press-release and BBC Business URLs are confirmed official but were not fetched directly. If one is down the others still work. If all are down, the 07:00 news waits and retries inside the catch-up window rather than sending a broken message. Only headline + link + source name are used, never article text.
- **A lot of small commits.** During the week the bot commits `state/` when something changes (at most roughly once an hour for the calendar cache, plus one per send). This is normal. Those commits are marked `[skip ci]`.
- **GitHub switches scheduled workflows off after 60 days with no repo activity.** Two protections: the bot's own state commits count as activity, and `.github/workflows/keepalive.yml` re-enables the bot's schedule once a week through the GitHub API. If GitHub ever emails you that the schedule was disabled, go to **Actions > RDFX bot > Enable workflow** and it's fixed.
- **No financial advice.** The messages are education and reminders. Wording is yours; keep it that way.

### Security summary
- Token and chat ID only in GitHub Secrets; only passed to the one step that sends. Never in code or commits.
- URLs containing the token are never printed. Errors and log lines are scrubbed of the token and chat ID.
- The workflow has minimal permissions (`contents: write` only to save state). Third-party actions are pinned to full commit SHAs (Dependabot opens a monthly PR to update them). No `pull_request_target`. `.env` files are git-ignored.
- All external text (headlines, event names) is cleaned and HTML-escaped; links must be `https` and on the source's own domain. Nothing from a feed can add markup or links.

---

## 6. How to add a new message type

A message type is one small Python file plus wording in a text file. Example: a Friday weekly reminder.

**1. Wording** : add to `messages/templates.yaml`:
```yaml
weekly_reminder:
  text: |
    📌 RDFX | WEEKLY REMINDER

    Review your trades. Plan next week. **Stay disciplined.**
```

**2. Code** : create `src/rdfx_bot/kinds/weekly_reminder.py`:
```python
from ..context import Context
from ..models import Message
from ..textutil import render
from .registry import register


@register("weekly_reminder")
def build_weekly_reminder(ctx: Context) -> Message | None:
    text = ctx.cfg.messages["templates"]["weekly_reminder"]["text"]
    return Message(text=render(text), kind="weekly_reminder")
```
(Return `None` to skip quietly. To add a button: `Message(text=..., buttons=[Button("LABEL", ctx.cfg.link("VIP_URL"))])`.)

**3. Register it** : in `src/rdfx_bot/kinds/__init__.py` add `weekly_reminder` to the import line.

**4. Schedule it** : in `config/schedule.yaml` under `messages:`
```yaml
  weekly_reminder:
    kind: weekly_reminder
    enabled: true
    days: [fri]
    times: ["17:00"]
```

**5. (Optional) Test button** : add `weekly_reminder` to the two lists in `.github/workflows/bot.yml` (the dropdown and the `case` line) so it shows in the Run workflow menu.

Then run a dry run from the Actions tab. Rotating pools (like funnels) are even easier: copy `kinds/funnel.py` and add a pool to `messages/funnels.yaml`.

---

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| Nothing arrives in Telegram | Run `preview` as a dry run first. If that works, send `london` live and read the **Run the bot** step for the error. |
| `Telegram refused the message (HTTP 401)` | Token wrong or revoked. Make a new token in BotFather and update the secret. |
| `HTTP 400 ... chat not found` | Wrong chat ID, or the bot is not in the channel/group. Re-do steps 2 and 3. |
| `HTTP 403 ... bot is not a member / can't post` | Make the bot an **admin** of the channel with Post Messages. |
| `SETUP ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set` | Secret names must match exactly, with no extra spaces. |
| Yellow warning "Config check found problems" | You made a typo in a message or config file. The log lists the file and line of the problem. Messages already sent are unaffected. |
| A message looks plain (no bold) | Telegram rejected the formatting, so the bot resent it as plain text. Check for a stray `<`, `>` or `&` in that message. |
| Calendar / alerts not arriving | Check the log for "calendar feed unavailable". Add key events by hand in `events.json` in the meantime. |
| News says "nothing major" for everything | Normal on quiet days. Add or loosen keywords in `config/sources.yaml`. |
| Message arrived late | GitHub's scheduler was busy (see section 5). If it is later than the catch-up window it is skipped instead. |
| Message skipped altogether | Late past the catch-up window, a weekend, a blocked date, the message is switched off, or the kill switch is on. |
| Run fails at **Save state** | Branch protection is blocking the bot's commit, or Settings > Actions > General > Workflow permissions is set to read-only. Allow read and write. |
| Schedule stopped running | Actions > RDFX bot > **Enable workflow**. |
| Duplicates | Should not happen. If it does, check `state/sent.json` is not being reset by a manual edit. |
| Want to re-send something | Run workflow with that message selected and Dry run un-ticked. Manual sends don't affect the schedule. |

GitHub emails you when a run fails, so problems don't go unnoticed.

---

## 8. Upgrade ideas

- **Images / charts**: attach a daily levels chart or branded graphic (`sendPhoto`).
- **Several channels**: send the same message to a free and a VIP channel (a list of chat IDs).
- **AI-written briefings**: summarise the headlines in your voice (would need an API key, so it is not free).
- **Telegram commands**: `/calendar`, `/sessions` answered on demand (needs an always-on listener or a free webhook host).
- **Win/loss recap posts**: a weekly results card fed from a simple sheet or JSON file.
- **Level-up the calendar**: actual vs forecast posted after release.
- **Pinned message refresh**: re-pin the VIP / mentorship post weekly.
- **Per-message analytics**: UTM-tagged links to see which funnel posts convert.

---

## 9. Assumptions, and what you must fill in

**You must fill in:** only `TIKTOK_URL` in `config/links.yaml` (empty on purpose; everything works without it).

**Assumptions I made:**
- Weekend means **no sends at all**, including the 00:00 Asian open (Mon-Fri UK dates only). Change `active_days` in `settings.yaml` to alter this.
- The 00:00 Asian open follows your request literally. Tokyo's cash open is 00:00 UK in winter but 01:00 in summer (BST); move it in `schedule.yaml` if you'd rather match.
- Funnels: mentorship Mon/Wed/Fri 11:00; VIP Tue/Thu 11:00 and every weekday 18:00. Socials 12:00 and 20:00 weekdays. Message choice is random but never the same one twice in a row per pool.
- Several events at the same minute become **one** alert message (`group_same_time: false` splits them).
- The catch-up window is 45 minutes for everything, including the 08:30 calendar and 07:00 news (which retry inside that window if a feed is down).
- High/Medium only, USD/GBP/EUR/JPY. Holidays and Low impact are ignored.
- Bold in the calendar goes on big movers (CPI, inflation, NFP, employment change, FOMC statement / press conference, interest and bank rates, GDP, unemployment). Speeches are not bold. The list is in `config/sources.yaml`.
- Telegram link previews are switched off so the posts stay clean.
- The 5th social message (YouTube) is my draft. Please approve it.
- The Instagram button goes to the link you supplied (`ryan_drewery6`), with no QR-tracking parameters.

---

## 10. Project layout

```
.github/workflows/bot.yml        every-5-minutes run + manual "Run workflow" menu
.github/workflows/keepalive.yml  weekly re-enable of the schedule
config/settings.yaml             kill switch, blocked dates, timezone
config/schedule.yaml             times, days, on/off per message, catch-up window
config/links.yaml                every link (VIP, mentorship, Instagram, YouTube, TikTok)
config/sources.yaml              calendar feed, RSS whitelist, keyword rules
messages/*.yaml                  ALL message wording
events.json                      optional manual events
state/                           sent history + calendar cache (written by the bot)
src/rdfx_bot/                    the program (kinds/ = one file per message type)
tests/                           automated tests
```

**Run the tests / try it locally** (optional; needs Python 3.11+):
```bash
pip install -r requirements-dev.txt
python -m pytest                              # 124 tests
PYTHONPATH=src python -m rdfx_bot check       # validate config + messages
PYTHONPATH=src python -m rdfx_bot preview     # print every message type
PYTHONPATH=src python -m rdfx_bot run --dry-run --now 2026-11-23T08:00   # pretend it is Mon 08:00 UK
```
