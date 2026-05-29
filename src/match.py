"""Match post text to companies by name OR cashtag.

Rules (per project decisions, refined against real data):
- Company name match: case-insensitive, whole-phrase. Counts freely, EXCEPT
  names that collapse to a generic word (data/name_stoplist.txt) are skipped.
- Cashtag ($AAPL): counts if the ticker is in the universe.
- Bare tickers (AAPL, HAL, DE) are NOT matched: Trump's heavy ALL-CAPS usage
  makes them almost pure noise, and he references companies by name anyway.
- Share classes (NWSA/NWS, GOOGL/GOOG, FOX/FOXA) merge into one company.
- Duplicate/retweeted posts are counted once.
- A company is counted at most once per post.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from companies import Company, clean_name, load_name_stoplist

_NONWORD = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")
_CASHTAG = re.compile(r"\$([A-Za-z]{1,6})\b")


@dataclass
class Index:
    symbols: set[str]                             # every ticker in the universe
    sym_to_canon: dict[str, str]                  # any ticker -> canonical ticker
    name_patterns: list[tuple[str, re.Pattern]]   # (canonical, whole-phrase regex)
    by_symbol: dict[str, Company]                 # canonical -> merged Company


def _normalize(text: str) -> str:
    """Lowercase + strip punctuation for whole-phrase name matching."""
    return _WS.sub(" ", _NONWORD.sub(" ", text.lower())).strip()


def build_index(companies: list[Company], apply_name_stoplist: bool = True) -> Index:
    # High-recall mode (apply_name_stoplist=False) is used by the LLM hybrid:
    # surface every name match and let the model disambiguate in context.
    name_stop = load_name_stoplist() if apply_name_stoplist else set()

    # Group share classes: same cleaned name => same company.
    groups: dict[str, list[Company]] = {}
    for c in companies:
        groups.setdefault(c.name_clean or clean_name(c.name), []).append(c)

    symbols = {c.symbol for c in companies}
    sym_to_canon: dict[str, str] = {}
    by_symbol: dict[str, Company] = {}
    name_patterns: list[tuple[str, re.Pattern]] = []

    for name_clean, members in groups.items():
        canon = min(members, key=lambda c: (len(c.symbol), c.symbol)).symbol
        merged = Company(
            symbol=canon,
            name=next(m.name for m in members if m.symbol == canon),
            name_clean=name_clean,
            indices=set().union(*(m.indices for m in members)),
        )
        by_symbol[canon] = merged
        for m in members:
            sym_to_canon[m.symbol] = canon
        if len(name_clean) >= 2 and name_clean not in name_stop:
            name_patterns.append((canon, re.compile(rf"\b{re.escape(name_clean)}\b")))

    return Index(symbols, sym_to_canon, name_patterns, by_symbol)


def match_candidates(text: str, index: Index) -> tuple[set[str], set[str]]:
    """Return (cashtag_hits, name_hits) as canonical tickers for a single post.
    Cashtags are explicit and unambiguous; name hits are collision-prone."""
    cashtags: set[str] = set()
    for m in _CASHTAG.finditer(text):
        sym = m.group(1).upper()
        if sym in index.symbols:
            cashtags.add(index.sym_to_canon[sym])

    names: set[str] = set()
    norm = _normalize(text)
    for canon, pat in index.name_patterns:
        if pat.search(norm):
            names.add(canon)

    return cashtags, names


def match_post(text: str, index: Index) -> set[str]:
    """Return the set of canonical company tickers mentioned in a single post."""
    cashtags, names = match_candidates(text, index)
    return cashtags | names


def count_mentions(posts: list[str], companies: list[Company]) -> Counter:
    """Count companies across posts, at most once per post (text-only API)."""
    index = build_index(companies)
    counts: Counter = Counter()
    for text in posts:
        for sym in match_post(text or "", index):
            counts[sym] += 1
    return counts


EXCERPT_LEN = 200

# Strip a self-retweet prefix so an "RT @realDonaldTrump..." repost dedupes
# against the original (the archive includes both, inflating counts).
_RT_PREFIX = re.compile(r"(?i)^\s*rt\s+@realdonaldtrump\s*")


def _dedupe_key(text: str) -> str:
    return _WS.sub(" ", _RT_PREFIX.sub("", text).lower()).strip()


def dedupe_posts(posts: list[dict]) -> list[dict]:
    """Drop duplicate / self-retweeted posts, preserving first occurrence."""
    seen: set[str] = set()
    out: list[dict] = []
    for p in posts:
        key = _dedupe_key(p.get("text") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def excerpt_of(text: str) -> str:
    return text if len(text) <= EXCERPT_LEN else text[:EXCERPT_LEN].rstrip() + "…"


def build_candidates(posts: list[dict], companies: list[Company]) -> list[dict]:
    """High-recall candidate records for offline/LLM adjudication. Each record is
    one deduped post with its cashtag-confirmed tickers and the ambiguous company
    NAME matches (each with a global id) that need a yes/no judgment."""
    index = build_index(companies, apply_name_stoplist=False)
    records: list[dict] = []
    cid = 0
    for p in dedupe_posts(posts):
        text = p.get("text") or ""
        cashtags, names = match_candidates(text, index)
        cands = []
        for canon in sorted(n for n in names if n not in cashtags):
            cands.append({"id": cid, "ticker": canon,
                          "company": index.by_symbol[canon].name})
            cid += 1
        records.append({
            "url": p.get("url"),
            "created_at": p.get("created_at"),
            "text": text,
            "confirmed": sorted(cashtags),
            "candidates": cands,
        })
    return records


def _verdict(verdicts: dict, cid: int) -> bool:
    # verdicts keys may be int or str (JSON round-trip)
    return bool(verdicts.get(str(cid), verdicts.get(cid, False)))


def finalize_from_records(
    records: list[dict], verdicts: dict
) -> tuple[Counter, dict[str, list[dict]]]:
    """Combine candidate records with adjudication verdicts ({id: bool}) into
    counts + refs. Confirmed cashtags always count; name candidates count only
    when their verdict is true. One company per post."""
    counts: Counter = Counter()
    refs: dict[str, list[dict]] = {}
    for r in records:
        final = set(r.get("confirmed", []))
        for c in r.get("candidates", []):
            if _verdict(verdicts, c["id"]):
                final.add(c["ticker"])
        excerpt = excerpt_of(r.get("text") or "")
        for canon in final:
            counts[canon] += 1
            refs.setdefault(canon, []).append({
                "url": r.get("url"),
                "created_at": r.get("created_at"),
                "excerpt": excerpt,
            })
    return counts, refs


def count_with_references(
    posts: list[dict], companies: list[Company]
) -> tuple[Counter, dict[str, list[dict]], Index]:
    """Like count_mentions, but each post is a dict with at least 'text' (and
    optional 'id'/'url'/'created_at'). Duplicate/retweeted posts are counted
    once. Returns counts, per-company source-post references, and the index."""
    index = build_index(companies)
    counts: Counter = Counter()
    refs: dict[str, list[dict]] = {}
    for p in dedupe_posts(posts):
        text = p.get("text") or ""
        for sym in match_post(text, index):
            counts[sym] += 1
            excerpt = excerpt_of(text)
            refs.setdefault(sym, []).append({
                "url": p.get("url"),
                "created_at": p.get("created_at"),
                "excerpt": excerpt,
            })
    return counts, refs, index
