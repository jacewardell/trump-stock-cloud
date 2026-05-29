"""Unit tests for company matching logic (name OR cashtag; no bare tickers)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from companies import Company, clean_name  # noqa: E402
from match import (  # noqa: E402
    build_candidates,
    build_index,
    count_mentions,
    count_with_references,
    finalize_from_records,
    match_post,
)


def _co(symbol, name):
    return Company(symbol=symbol, name=name, name_clean=clean_name(name))


UNIVERSE = [
    _co("AAPL", "Apple Inc."),
    _co("TSLA", "Tesla, Inc."),
    _co("ALL", "Allstate Corporation"),
    _co("GM", "General Motors"),
    _co("HAL", "Halliburton"),
]


def hits(text):
    return match_post(text, build_index(UNIVERSE))


def test_company_name_lowercase():
    assert hits("i love apple products") == {"AAPL"}


def test_company_name_with_suffix_matches_clean():
    assert "TSLA" in hits("Tesla is up today")


def test_cashtag_matches():
    assert hits("buying $TSLA today") == {"TSLA"}


def test_bare_ticker_is_not_matched():
    # No bare-ticker matching anymore: ALL-CAPS "AAPL" alone should not count.
    assert hits("AAPL to the moon") == set()


def test_bare_caps_word_collision_ignored():
    # "HAL" in caps must NOT match Halliburton (the noise we removed)
    assert hits("Congratulations HAL ROGERS on your win") == set()


def test_halliburton_matches_by_name():
    assert hits("Halliburton reported earnings") == {"HAL"}


def test_lowercase_word_no_match():
    assert hits("it is on the table") == set()


def test_multiword_company_name():
    assert hits("General Motors had a great quarter") == {"GM"}


def test_name_and_cashtag_same_post_counted_once():
    counts = count_mentions(["Apple is great and $AAPL is up"], UNIVERSE)
    assert counts["AAPL"] == 1


def test_counts_across_multiple_posts():
    posts = ["Tesla is great", "I bought $TSLA", "apple news", "$AAPL again"]
    counts = count_mentions(posts, UNIVERSE)
    assert counts["TSLA"] == 2
    assert counts["AAPL"] == 2


def test_empty_and_none_posts():
    assert count_mentions(["", None], UNIVERSE) == {}


# --- share-class merge + generic-name block (uses the real name_stoplist) ---

MERGE_UNIVERSE = [
    _co("NWSA", "News Corp (Class A)"),
    _co("NWS", "News Corp (Class B)"),
    _co("GOOGL", "Alphabet Inc. (Class A)"),
    _co("GOOG", "Alphabet Inc. (Class C)"),
]


def mhits(text):
    return match_post(text, build_index(MERGE_UNIVERSE))


def test_generic_name_blocked():
    # 'News Corp' -> 'news' is in the name stoplist, so the word 'news' is ignored
    assert mhits("the fake news is at it again") == set()


def test_blocked_name_still_matches_via_cashtag():
    assert mhits("$NWSA reported earnings") == {"NWS"}


def test_share_classes_merge_to_one_canonical():
    assert mhits("Alphabet and $GOOG together") == {"GOOG"}


def test_share_class_counted_once_per_post():
    counts = count_mentions(["$GOOGL and $GOOG and Alphabet"], MERGE_UNIVERSE)
    assert counts["GOOG"] == 1
    assert "GOOGL" not in counts


# --- references + dedup ---

def test_references_attach_source_urls():
    posts = [
        {"text": "Apple is great $AAPL", "url": "u1", "created_at": "t1"},
        {"text": "buying $TSLA", "url": "u2", "created_at": "t2"},
        {"text": "apple again", "url": "u3", "created_at": "t3"},
    ]
    counts, refs, _ = count_with_references(posts, UNIVERSE)
    assert counts["AAPL"] == 2
    assert [r["url"] for r in refs["AAPL"]] == ["u1", "u3"]
    assert refs["TSLA"][0]["url"] == "u2"
    assert refs["AAPL"][0]["excerpt"] == "Apple is great $AAPL"


def test_retweets_and_duplicates_counted_once():
    posts = [
        {"text": "Tesla is winning bigly", "url": "orig"},
        {"text": "RT @realDonaldTrumpTesla is winning bigly", "url": "rt"},
        {"text": "Tesla is winning bigly", "url": "dup"},
    ]
    counts, refs, _ = count_with_references(posts, UNIVERSE)
    assert counts["TSLA"] == 1
    assert [r["url"] for r in refs["TSLA"]] == ["orig"]


# --- emit / finalize (offline adjudication flow) ---

def test_build_candidates_splits_cashtags_and_names():
    posts = [{"text": "Apple and $TSLA today", "url": "u1"}]
    records = build_candidates(posts, UNIVERSE)
    assert records[0]["confirmed"] == ["TSLA"]          # cashtag auto-confirmed
    cands = records[0]["candidates"]
    assert [c["ticker"] for c in cands] == ["AAPL"]      # name needs judgment
    assert cands[0]["id"] == 0


def test_finalize_applies_verdicts():
    records = build_candidates(
        [{"text": "Apple is great and Allstate too", "url": "u1"}], UNIVERSE)
    # candidates are AAPL (id 0) and ALL (id 1) by sorted ticker
    verdicts = {"0": True, "1": False}
    counts, refs = finalize_from_records(records, verdicts)
    assert counts["AAPL"] == 1
    assert "ALL" not in counts
    assert refs["AAPL"][0]["url"] == "u1"


def test_finalize_keeps_cashtags_with_no_verdicts():
    records = build_candidates([{"text": "buying $TSLA", "url": "u1"}], UNIVERSE)
    counts, _ = finalize_from_records(records, {})
    assert counts["TSLA"] == 1
