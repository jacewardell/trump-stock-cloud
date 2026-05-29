"""Daily pipeline: scrape -> match -> count -> render bar chart + JSON.

Modes:
  (default)            scrape + match (--match llm|dict) + render in one shot
  --emit-candidates    scrape + write candidates/DATE.json for offline adjudication
  --finalize           combine candidates/DATE.json + verdicts/DATE.json -> render

The emit/finalize split lets a scheduled Claude Code job adjudicate the
candidates file (writing verdicts/DATE.json) without an Anthropic API key.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cloud import render_chart, write_json  # noqa: E402
from companies import load_companies  # noqa: E402
from match import (  # noqa: E402
    build_candidates,
    build_index,
    count_with_references,
    finalize_from_records,
)

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_DIR = ROOT / "candidates"
VERDICTS_DIR = ROOT / "verdicts"


def _load_posts_from_file(path: str) -> list[dict]:
    """Test helper: a JSON list of strings, or list of objects with a 'text' key
    (and optional 'url'/'created_at'). Returns normalized post dicts."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for item in data:
        if isinstance(item, str):
            out.append({"text": item, "url": None, "created_at": None})
        elif item.get("text"):
            out.append({
                "text": item["text"],
                "url": item.get("url"),
                "created_at": item.get("created_at"),
            })
    return out


def _get_posts(args, handle: str) -> list[dict]:
    if args.posts_file:
        posts = _load_posts_from_file(args.posts_file)
        print(f"Loaded {len(posts)} posts from {args.posts_file}")
        return posts
    from scrape import fetch_posts
    since = datetime.now(timezone.utc) - timedelta(hours=args.since_hours)
    fetched = fetch_posts(handle, since, source=args.source)
    posts = [
        {"id": p.id, "url": p.url,
         "created_at": p.created_at.isoformat() if p.created_at else None,
         "text": p.text}
        for p in fetched
    ]
    print(f"Fetched {len(posts)} posts for @{handle} since {since.isoformat()}")
    return posts


def _render_and_report(counts, refs, by_symbol, date_str, handle, post_count) -> int:
    png = render_chart(counts, by_symbol, date_str, handle, post_count)
    js = write_json(counts, by_symbol, date_str, handle, post_count, refs)
    print(f"\nTop mentions for {date_str}:")
    for sym, cnt in counts.most_common(10):
        print(f"  {cnt:>3}  {sym:<6} {by_symbol[sym].name}")
    if not counts:
        print("  (none)")
    print(f"\nWrote {png}\nWrote {js}")
    return 0


def emit_candidates(args, companies, handle, date_str) -> int:
    posts = _get_posts(args, handle)
    records = build_candidates(posts, companies)
    n_cands = sum(len(r["candidates"]) for r in records)
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    path = CANDIDATES_DIR / f"{date_str}.json"
    path.write_text(json.dumps(
        {"date": date_str, "handle": handle, "post_count": len(records),
         "records": records}, indent=2), encoding="utf-8")
    print(f"Wrote {path}")
    print(f"{len(records)} posts | {n_cands} name candidates to adjudicate")
    print(f"Next: write {VERDICTS_DIR / (date_str + '.json')} as {{id: true|false}}, "
          f"then run --finalize --date {date_str}")
    return 0


def finalize(args, companies, handle, date_str) -> int:
    cand_path = CANDIDATES_DIR / f"{date_str}.json"
    data = json.loads(cand_path.read_text(encoding="utf-8"))
    records = data["records"]

    verdict_path = VERDICTS_DIR / f"{date_str}.json"
    if verdict_path.exists():
        verdicts = json.loads(verdict_path.read_text(encoding="utf-8"))
    else:
        print(f"WARNING: {verdict_path} missing; counting cashtags only")
        verdicts = {}

    counts, refs = finalize_from_records(records, verdicts)
    by_symbol = build_index(companies).by_symbol
    return _render_and_report(counts, refs, by_symbol, date_str,
                              data.get("handle", handle), data.get("post_count", 0))


def run(args) -> int:
    load_dotenv()
    handle = args.handle or os.getenv("TARGET_HANDLE", "realDonaldTrump")
    date_str = args.date or datetime.now(ET).strftime("%Y-%m-%d")

    companies = load_companies(refresh=args.refresh_companies)
    print(f"Universe: {len(companies)} companies")

    if args.finalize:
        return finalize(args, companies, handle, date_str)
    if args.emit_candidates:
        return emit_candidates(args, companies, handle, date_str)

    posts = _get_posts(args, handle)
    match_mode = args.match
    if match_mode == "llm" and not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set; falling back to --match dict")
        match_mode = "dict"

    if match_mode == "llm":
        from adjudicate import count_with_llm
        print("Matching with LLM adjudication (Claude)")
        counts, refs, index = count_with_llm(posts, companies)
    else:
        counts, refs, index = count_with_references(posts, companies)

    return _render_and_report(counts, refs, index.by_symbol, date_str, handle, len(posts))


def main():
    p = argparse.ArgumentParser(description="Trump -> stock mentions bar chart")
    p.add_argument("--date", help="Output date label (YYYY-MM-DD, ET)")
    p.add_argument("--handle", help="Override target handle")
    p.add_argument("--since-hours", type=int, default=24,
                   help="Look back this many hours (default 24)")
    p.add_argument("--source", choices=["archive", "truthbrush"], default="archive",
                   help="Post source: 'archive' (no account) or 'truthbrush' (login)")
    p.add_argument("--match", choices=["llm", "dict"], default="llm",
                   help="One-shot matching: 'llm' (needs API key) or 'dict'")
    p.add_argument("--emit-candidates", action="store_true",
                   help="Write candidates/DATE.json for offline adjudication")
    p.add_argument("--finalize", action="store_true",
                   help="Combine candidates + verdicts/DATE.json and render")
    p.add_argument("--refresh-companies", action="store_true",
                   help="Re-fetch the S&P500 + Nasdaq100 lists")
    p.add_argument("--posts-file",
                   help="Read posts from a JSON file instead of scraping (testing)")
    sys.exit(run(p.parse_args()))


if __name__ == "__main__":
    main()
