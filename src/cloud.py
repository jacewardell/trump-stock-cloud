"""Render the daily bar chart and write the counts JSON."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless / no display
import matplotlib.pyplot as plt  # noqa: E402

from companies import Company, _SUFFIXES  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
MAX_BARS = 30  # cap for readability; counts beyond this are noted in the title

_PARENS = re.compile(r"\([^)]*\)")
_TRAILING_JUNK = re.compile(r"[\s.,]+$")


def display_name(company: Company) -> str:
    """Readable label: drop parentheticals + corporate suffixes."""
    label = _PARENS.sub("", company.name)        # remove "(Class A)", "(The)"
    label = _SUFFIXES.sub("", label)             # remove Inc/Corp/Company/...
    label = label.replace(",", " ")
    label = re.sub(r"\s+", " ", label).strip()
    label = _TRAILING_JUNK.sub("", label).strip()
    return label or company.symbol


def write_json(
    counts: Counter, by_symbol: dict[str, Company], date_str: str,
    handle: str, post_count: int, refs: dict[str, list[dict]] | None = None,
    out_dir: Path = OUTPUT_DIR,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    refs = refs or {}
    companies = [
        {
            "symbol": sym,
            "name": by_symbol[sym].name,
            "count": cnt,
            "indices": sorted(by_symbol[sym].indices),
            "posts": refs.get(sym, []),
        }
        for sym, cnt in counts.most_common()
    ]
    payload = {
        "date": date_str,
        "handle": handle,
        "post_count": post_count,
        "companies": companies,
    }
    path = out_dir / f"{date_str}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def render_chart(
    counts: Counter, by_symbol: dict[str, Company], date_str: str,
    handle: str, post_count: int, out_dir: Path = OUTPUT_DIR,
) -> Path:
    """Horizontal bar chart of companies by mention count (most at top)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date_str}.png"

    top = counts.most_common(MAX_BARS)
    title = f"Companies mentioned by @{handle} — {date_str}  ({post_count} posts)"
    if len(counts) > MAX_BARS:
        title += f"  [top {MAX_BARS} of {len(counts)}]"

    if not top:
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.text(0.5, 0.5, f"No company mentions\n{date_str}",
                ha="center", va="center", fontsize=22)
        ax.axis("off")
        fig.savefig(path, bbox_inches="tight", dpi=150)
        plt.close(fig)
        return path

    # Ascending so the largest count sits at the top of the chart.
    top = top[::-1]
    labels = [display_name(by_symbol[sym]) for sym, _ in top]
    vals = [cnt for _, cnt in top]

    fig, ax = plt.subplots(figsize=(9, max(3.0, 0.42 * len(top) + 1.5)))
    bars = ax.barh(labels, vals, color="#2a7ab0")
    for b, v in zip(bars, vals):
        ax.text(v + max(vals) * 0.01 + 0.02, b.get_y() + b.get_height() / 2,
                str(v), va="center", fontsize=11)
    ax.set_xlabel("Mentions")
    ax.set_title(title)
    ax.margins(x=0.08)
    from matplotlib.ticker import MaxNLocator
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
