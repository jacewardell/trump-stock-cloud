"""Tests for the LLM hybrid matcher (adjudicator injected, no API calls)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from adjudicate import count_with_llm  # noqa: E402
from companies import Company, clean_name  # noqa: E402


def _co(symbol, name):
    return Company(symbol=symbol, name=name, name_clean=clean_name(name))


UNIVERSE = [
    _co("AAPL", "Apple Inc."),
    _co("TSLA", "Tesla, Inc."),
    _co("SO", "Southern Company"),
]


def confirm_all(cands):
    return {c["id"]: True for c in cands}


def reject_southern(cands):
    return {c["id"]: "Southern" not in c["company"] for c in cands}


def test_cashtag_auto_confirmed_without_llm():
    seen = []
    counts, refs, _ = count_with_llm(
        [{"text": "buying $TSLA today", "url": "u1"}], UNIVERSE,
        adjudicator=lambda c: seen.append(c) or {},
    )
    assert counts["TSLA"] == 1
    assert seen == []  # cashtag-only post: LLM not called at all


def test_name_candidate_confirmed_by_llm():
    counts, refs, _ = count_with_llm(
        [{"text": "Apple is doing great", "url": "u1"}], UNIVERSE,
        adjudicator=confirm_all,
    )
    assert counts["AAPL"] == 1
    assert refs["AAPL"][0]["url"] == "u1"


def test_name_candidate_rejected_by_llm():
    # "southern" matches Southern Company at high recall, but the LLM rejects it
    counts, _, _ = count_with_llm(
        [{"text": "secure the southern border now"}], UNIVERSE,
        adjudicator=reject_southern,
    )
    assert "SO" not in counts


def test_mixed_post_counts_confirmed_only():
    counts, _, _ = count_with_llm(
        [{"text": "Apple is great but the southern border is open"}], UNIVERSE,
        adjudicator=reject_southern,
    )
    assert counts["AAPL"] == 1
    assert "SO" not in counts


def test_duplicate_posts_deduped():
    counts, _, _ = count_with_llm(
        [
            {"text": "Apple is great", "url": "a"},
            {"text": "RT @realDonaldTrumpApple is great", "url": "b"},
        ],
        UNIVERSE, adjudicator=confirm_all,
    )
    assert counts["AAPL"] == 1
