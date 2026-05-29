"""Load and cache the S&P 500 + Nasdaq-100 company universe (name + ticker)."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE = DATA_DIR / "companies.csv"

SOURCES = {
    "sp500": "https://yfiua.github.io/index-constituents/constituents-sp500.csv",
    "nasdaq100": "https://yfiua.github.io/index-constituents/constituents-nasdaq100.csv",
}

# Corporate suffixes/noise stripped when deriving a matchable name.
_SUFFIXES = re.compile(
    r"\b(incorporated|inc|corporation|corp|company|co|ltd|limited|llc|plc|"
    r"holdings|holding|group|class\s+[abc]|the)\b",
    re.IGNORECASE,
)
_NONWORD = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


@dataclass
class Company:
    symbol: str
    name: str
    name_clean: str = ""
    indices: set[str] = field(default_factory=set)


def clean_name(name: str) -> str:
    """Lowercase, drop corporate suffixes and punctuation, collapse whitespace."""
    s = name.lower()
    s = _SUFFIXES.sub(" ", s)
    s = _NONWORD.sub(" ", s)
    return _WS.sub(" ", s).strip()


def refresh_companies() -> list[Company]:
    """Fetch both indices, union by ticker, write the cache, return companies."""
    by_symbol: dict[str, Company] = {}
    for index, url in SOURCES.items():
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        rows = csv.DictReader(resp.text.splitlines())
        for row in rows:
            sym = (row.get("Symbol") or "").strip().upper()
            name = (row.get("Name") or "").strip()
            if not sym or not name:
                continue
            comp = by_symbol.get(sym)
            if comp is None:
                comp = Company(symbol=sym, name=name, name_clean=clean_name(name))
                by_symbol[sym] = comp
            comp.indices.add(index)

    companies = sorted(by_symbol.values(), key=lambda c: c.symbol)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with CACHE.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "name", "name_clean", "indices"])
        for c in companies:
            w.writerow([c.symbol, c.name, c.name_clean, "|".join(sorted(c.indices))])
    return companies


def load_companies(refresh: bool = False) -> list[Company]:
    """Return cached companies, fetching fresh if missing or refresh=True."""
    if refresh or not CACHE.exists():
        return refresh_companies()
    companies: list[Company] = []
    with CACHE.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            companies.append(
                Company(
                    symbol=row["symbol"],
                    name=row["name"],
                    name_clean=row["name_clean"],
                    indices=set(row["indices"].split("|")) if row["indices"] else set(),
                )
            )
    return companies


def _load_word_file(filename: str, *, upper: bool) -> set[str]:
    path = DATA_DIR / filename
    out: set[str] = set()
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(line.upper() if upper else line.lower())
    return out


def load_name_stoplist() -> set[str]:
    """Cleaned company names too generic to match by name (tickers still count)."""
    return _load_word_file("name_stoplist.txt", upper=False)


if __name__ == "__main__":
    comps = refresh_companies()
    print(f"Cached {len(comps)} companies to {CACHE}")
