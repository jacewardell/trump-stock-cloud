"""Tests for the real-time poller (scrape + email injected; no network/SMTP)."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import poll  # noqa: E402
from companies import Company, clean_name  # noqa: E402
from match import count_with_references  # noqa: E402

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


def _co(symbol, name):
    return Company(symbol=symbol, name=name, name_clean=clean_name(name))


UNIVERSE = [_co("AAPL", "Apple Inc."), _co("TSLA", "Tesla, Inc.")]


class _FakePost:
    def __init__(self, pid, text, url):
        self.id, self.text, self.url = pid, text, url
        self.created_at = NOW


def _wire(monkeypatch, tmp_path, posts):
    """Point state at tmp, stub scrape + company load, capture sent alerts."""
    monkeypatch.setattr(poll, "STATE_DIR", tmp_path)
    monkeypatch.setattr(poll, "STATE_PATH", tmp_path / "seen.json")
    monkeypatch.setattr(poll, "load_companies", lambda *a, **k: UNIVERSE)
    fake_scrape = type(sys)("scrape")
    fake_scrape.fetch_posts = lambda handle, since: posts
    monkeypatch.setitem(sys.modules, "scrape", fake_scrape)
    return []


def _match(new_posts):
    _, refs, index = count_with_references(new_posts, UNIVERSE)
    return refs, index


def test_alerts_on_new_mention(monkeypatch, tmp_path):
    sent = _wire(monkeypatch, tmp_path, [_FakePost("1", "Apple is great", "u1")])
    n = poll.poll(now=NOW, matcher=_match, sender=lambda s, b: sent.append((s, b)))
    assert n == 1
    subject, body = sent[0]
    assert "AAPL" in subject and "Apple" in body


def test_no_mention_no_alert_but_marked_seen(monkeypatch, tmp_path):
    sent = _wire(monkeypatch, tmp_path, [_FakePost("1", "nothing here", "u1")])
    n = poll.poll(now=NOW, matcher=_match, sender=lambda s, b: sent.append((s, b)))
    assert n == 0 and sent == []
    assert "1" in poll._load_state()  # recorded so it's never rescanned


def test_seen_post_not_realerted(monkeypatch, tmp_path):
    posts = [_FakePost("1", "Apple is great", "u1")]
    sent = _wire(monkeypatch, tmp_path, posts)
    poll.poll(now=NOW, matcher=_match, sender=lambda s, b: sent.append((s, b)))
    poll.poll(now=NOW, matcher=_match, sender=lambda s, b: sent.append((s, b)))
    assert len(sent) == 1  # second cycle sees the same post, sends nothing


def test_new_post_after_first_cycle_alerts(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(poll, "STATE_DIR", tmp_path)
    monkeypatch.setattr(poll, "STATE_PATH", tmp_path / "seen.json")
    monkeypatch.setattr(poll, "load_companies", lambda *a, **k: UNIVERSE)
    send = lambda s, b: sent.append((s, b))

    posts1 = [_FakePost("1", "Apple is great", "u1")]
    fake = type(sys)("scrape"); fake.fetch_posts = lambda h, s: posts1
    monkeypatch.setitem(sys.modules, "scrape", fake)
    poll.poll(now=NOW, matcher=_match, sender=send)

    posts2 = posts1 + [_FakePost("2", "buying $TSLA", "u2")]
    fake.fetch_posts = lambda h, s: posts2
    poll.poll(now=NOW, matcher=_match, sender=send)
    assert len(sent) == 2 and "TSLA" in sent[1][0]


def test_dry_run_writes_no_state(monkeypatch, tmp_path):
    sent = _wire(monkeypatch, tmp_path, [_FakePost("1", "Apple is great", "u1")])
    poll.poll(now=NOW, matcher=_match, sender=lambda s, b: sent.append((s, b)),
              dry_run=True)
    assert sent == []  # dry-run never calls sender
    assert not (tmp_path / "seen.json").exists()
