"""Real-time poller: alert the instant a new Trump post mentions a company.

Meant to run frequently (every ~2 min via launchd) instead of the once-a-day
digest. Each cycle:

  1. Fetch posts from the last --lookback-min minutes.
  2. Drop any post id already handled (state/seen.json) so we never re-alert.
  3. Match the new posts (LLM adjudication if ANTHROPIC_API_KEY is set, else the
     dictionary + name-stoplist path — same fallback as main.py).
  4. Email one alert per new post that mentions a company (via notify's SMTP).
  5. Record EVERY new post id as seen (even zero-mention ones), so each post is
     scanned at most once.

Decoupled from the daily chart/history/digest, which still runs once a day.

Freshness note: the default archive source refreshes ~every 5 min, so real-world
latency from post to alert is roughly the poll interval + up to ~5 min.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))

from companies import load_companies  # noqa: E402
from notify import send_alert_email  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
STATE_PATH = STATE_DIR / "seen.json"
RETENTION_DAYS = 3  # prune seen ids older than this to bound the state file


def _load_state() -> dict[str, str]:
    """Return {post_id: created_at_iso} of posts already handled."""
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return dict(data.get("seen", {}))
    except (ValueError, OSError):
        return {}


def _save_state(seen: dict[str, str], now: datetime) -> None:
    cutoff = now - timedelta(days=RETENTION_DAYS)
    pruned = {pid: ts for pid, ts in seen.items() if _after(ts, cutoff)}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"seen": pruned}, indent=2), encoding="utf-8"
    )


def _after(iso_ts: str | None, cutoff: datetime) -> bool:
    """True if iso_ts is missing/unparseable (keep it) or newer than cutoff."""
    if not iso_ts:
        return True
    try:
        return datetime.fromisoformat(iso_ts) >= cutoff
    except ValueError:
        return True


def _match(new_posts: list[dict], companies) -> tuple[dict, object]:
    """Match new posts. Returns (refs, index). LLM adjudication when an API key
    is present (few posts per cycle => cheap/fast), else dict + name-stoplist."""
    if os.getenv("ANTHROPIC_API_KEY"):
        from adjudicate import count_with_llm
        _, refs, index = count_with_llm(new_posts, companies)
    else:
        from match import count_with_references
        _, refs, index = count_with_references(new_posts, companies)
    return refs, index


def _mentions_by_url(refs: dict) -> dict[str, set[str]]:
    """Invert company->posts refs into post-url -> {tickers}."""
    by_url: dict[str, set[str]] = {}
    for sym, entries in refs.items():
        for e in entries:
            url = e.get("url")
            if url:
                by_url.setdefault(url, set()).add(sym)
    return by_url


def _alert_subject(symbols: list[str], by_symbol) -> str:
    head = ", ".join(symbols[:3]) + ("…" if len(symbols) > 3 else "")
    return f"Trump stock mention: {head}"


def _alert_body(post: dict, symbols: list[str], by_symbol) -> str:
    when = (post.get("created_at") or "").replace("T", " ")[:16]
    lines = [f"@realDonaldTrump mentioned {len(symbols)} "
             f"{'company' if len(symbols) == 1 else 'companies'} at {when} UTC:", ""]
    for sym in symbols:
        name = by_symbol[sym].name if sym in by_symbol else sym
        lines.append(f"  {sym}  {name}")
    lines += ["", "Post:", (post.get("text") or "").strip()]
    if post.get("url"):
        lines += ["", post["url"]]
    return "\n".join(lines)


def poll(lookback_min: int = 30, *, now: datetime | None = None,
         matcher=None, sender=None, dry_run: bool = False) -> int:
    """Run one poll cycle. Returns the number of new posts that triggered alerts.
    `matcher`/`sender` are injectable for tests (default: real match + real email)."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(minutes=lookback_min)

    from scrape import fetch_posts
    handle = os.getenv("TARGET_HANDLE", "realDonaldTrump")
    fetched = fetch_posts(handle, since)
    posts = [
        {"id": p.id, "url": p.url,
         "created_at": p.created_at.isoformat() if p.created_at else None,
         "text": p.text}
        for p in fetched
    ]

    seen = _load_state()
    new_posts = [p for p in posts if p["id"] not in seen]
    print(f"poll: {len(posts)} fetched since {since.isoformat()}, "
          f"{len(new_posts)} new")
    if not new_posts:
        return 0

    companies = load_companies()
    matcher = matcher or (lambda np: _match(np, companies))
    refs, index = matcher(new_posts)
    by_url = _mentions_by_url(refs)

    alerted = 0
    send = sender or send_alert_email
    for p in new_posts:
        symbols = sorted(by_url.get(p.get("url"), ()))
        if symbols:
            subject = _alert_subject(symbols, index.by_symbol)
            body = _alert_body(p, symbols, index.by_symbol)
            if dry_run:
                print(f"[dry-run] {subject}\n{body}\n")
            else:
                send(subject, body)
            alerted += 1
        # mark handled regardless of mentions so we never rescan this post
        seen[p["id"]] = p.get("created_at") or now.isoformat()

    if not dry_run:
        _save_state(seen, now)
    print(f"poll: alerted on {alerted} new post(s)")
    return alerted


def main():
    load_dotenv()
    p = argparse.ArgumentParser(description="Real-time Trump stock-mention alerter")
    p.add_argument("--lookback-min", type=int, default=30,
                   help="Fetch posts from the last N minutes (default 30)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print alerts instead of emailing; don't write state")
    args = p.parse_args()
    poll(lookback_min=args.lookback_min, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
