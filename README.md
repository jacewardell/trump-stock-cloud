# Trump → Stock Mentions Chart

Scrapes the last day of posts from a Truth Social account (default
`@realDonaldTrump`), cross-references the words against **S&P 500 + Nasdaq-100**
company names and tickers, and produces a daily **bar chart** ranking how often
each company was mentioned.

## What it does

1. **Scrape** all posts from the last 24h (`src/scrape.py`; default source is a
   public no-account archive, see below).
2. **Match** each post to companies. Two modes (`--match`):
   - **`llm` (default): hybrid.** The dictionary finds high-recall candidates
     (any company name + cashtags); cashtags auto-confirm; the ambiguous *name*
     matches are sent to Claude, which judges each in context ("is this post
     about Fox Corp, or just Fox News chatter?" / "'southern' = the company or
     the border?"). Needs `ANTHROPIC_API_KEY`; falls back to `dict` without it.
   - **`dict`: keyword only.** Company names + cashtags, with a hand-maintained
     name-block list (`data/name_stoplist.txt`) for generic-word collisions.
   - Common to both: **bare tickers are NOT matched** (Trump's ALL-CAPS usage
     makes short tickers like HAL/DE pure noise; he names companies anyway —
     tickers count only as cashtags). Share classes (NWSA/NWS, GOOGL/GOOG,
     FOX/FOXA) merge into one company. Duplicate / retweeted (`RT
     @realDonaldTrump`) posts are deduped. A company is counted **once per post**.
3. **Render** `output/YYYY-MM-DD.png` (horizontal bar chart, ranked) and
   `output/YYYY-MM-DD.json` (raw counts — kept stable so a history/frontend can
   be added later). Each company in the JSON includes a `posts` array of the
   source posts that mentioned it:

   ```json
   {
     "symbol": "AAPL", "name": "Apple Inc.", "count": 2,
     "indices": ["nasdaq100", "sp500"],
     "posts": [
       {"url": "https://truthsocial.com/@realDonaldTrump/123",
        "created_at": "2026-05-28T13:01:00+00:00",
        "excerpt": "Apple is doing GREAT things ... $AAPL to the moon!"}
     ]
   }
   ```

## Data source

The default `--source archive` pulls from a **public, no-account** JSON archive
of Trump's Truth Social posts, maintained by CNN's data team and auto-updated
every ~5 minutes (`https://ix.cnn.io/data/truth-social/truth_archive.json`). No
login, no Cloudflare. The optional `--source truthbrush` backend works for any
handle but needs a Truth Social account (uncomment truthbrush in
`requirements.txt` and fill in `.env`).

## Setup (Windows)

Requires Python 3.11+.

```bat
cd path\to\trump-stock-cloud
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

For the default LLM matching, set an Anthropic API key (otherwise it falls back
to `--match dict`):

```bat
copy .env.example .env
REM then edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

Cache the company universe once (auto-refreshes if the file is missing):

```bat
venv\Scripts\python.exe src\companies.py
```

## Run

```bat
REM Live, no account needed (default archive source):
venv\Scripts\python.exe src\main.py

REM Dry run with sample posts:
venv\Scripts\python.exe src\main.py --posts-file tests\sample_posts.json
```

Useful flags: `--date YYYY-MM-DD`, `--since-hours 24`, `--refresh-companies`,
`--source archive|truthbrush`, `--match llm|dict`.

## Browse the charts (GitHub Pages)

`index.html` is a static page that reads `output/manifest.json` (regenerated on
every run) and shows the latest chart, a date picker for past days, and an
all-time leaderboard. To publish it:

**Repo → Settings → Pages → Source: "Deploy from a branch" → Branch `main`,
folder `/ (root)` → Save.**

The site then lives at `https://jacewardell.github.io/trump-stock-cloud/` and
updates automatically each day when the run commits a new chart + manifest.
(Free for public repos; private repos need GitHub Pro.)

## Run daily on macOS — no API key (recommended)

This runs the whole pipeline locally on a schedule and does the LLM adjudication
with **headless Claude Code** (your Claude subscription), so **no Anthropic API
key is needed**. Output is committed back to this repo as the chart history.

**Prerequisites:**
- Python 3.11+
- **Claude Code CLI** installed and logged in — run `claude` once interactively
  to authenticate (this is what lets the scheduled job adjudicate for free).
- A clone of this repo with an `origin` remote you can **push to** (so the daily
  chart persists). `git config --global user.email/name` set.

**Install (one command):**

```bash
git clone https://github.com/jacewardell/trump-stock-cloud.git
cd trump-stock-cloud
bash setup_mac.sh
```

`setup_mac.sh` creates the venv, installs deps, caches the company list,
generates a launchd agent scheduled at **4:15pm ET in your machine's local
time**, and loads it. It prints warnings if `claude`, a git identity, or an
`origin` remote are missing.

**Daily flow** (`run_daily_local.sh`): emit candidates → headless `claude -p`
writes `verdicts/<date>.json` → finalize chart → commit & push.

```bash
bash run_daily_local.sh        # run now / backfill today
cat run.log                    # last run's log
launchctl print gui/$(id -u)/com.trumpstockcloud.daily | grep -i "next firing"
# uninstall:
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.trumpstockcloud.daily.plist \
  && rm ~/Library/LaunchAgents/com.trumpstockcloud.daily.plist
```

Caveats: the Mac must be **awake** at the scheduled time (launchd runs a missed
job on next wake, but skips it if the machine was off). The 24h archive lookback
means a fully-missed day can't be backfilled later than ~24h.

## Schedule at market close (Windows Task Scheduler)

Market close is **4:00 PM ET**. Schedule `run_daily.bat` a few minutes after.

1. Open **Task Scheduler** → **Create Task**.
2. **General**: name it "Trump Stock Cloud"; check "Run whether user is logged
   on or not".
3. **Triggers** → New: Daily (or Weekly Mon–Fri), start time **4:05 PM**
   (adjust for your machine's timezone vs. ET).
4. **Actions** → New: Program/script = full path to `run_daily.bat`; "Start in"
   = the project folder.
5. **Conditions**: optionally "Wake the computer to run this task".
6. Save (enter your Windows password if prompted).

Output lands in `output\`; run logs append to `output\run.log`.

## Tests

```bat
venv\Scripts\python.exe -m pytest tests\ -q
```

## Notes / known trade-offs

- The default archive source is a third-party feed; if it ever stops updating,
  switch to `--source truthbrush` or replace `_fetch_from_archive` in
  `src/scrape.py`. Nothing downstream changes.
- `--match llm` (default) resolves word/name collisions (intel=intelligence,
  Waters=Maxine Waters, southern=border, Fox News vs Fox Corp) contextually, so
  the `data/name_stoplist.txt` block list is only used by `--match dict`. Daily
  cost is negligible (a handful of posts/day); the all-time backfill (~27k posts)
  is where LLM cost would add up — use `--match dict` for bulk runs if needed.
- The JSON output schema is stable, so a static history page can be added later
  with no changes to the pipeline.
```
