"""Fetch posts for a handle since a cutoff time.

Two backends, selected by `source`:
- "archive" (default): a public, no-auth JSON archive of Trump's Truth Social
  posts, maintained by CNN's data team and auto-updated every ~5 minutes. No
  account, no Cloudflare. Covers @realDonaldTrump only.
- "truthbrush": the truthbrush library (needs a Truth Social login via env vars).
  Works for any handle but requires an account; kept as a fallback.

The rest of the app only depends on `fetch_posts(handle, since) -> list[Post]`,
so swapping or adding backends changes nothing downstream.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime

import requests

ARCHIVE_URL = "https://ix.cnn.io/data/truth-social/truth_archive.json"
ARCHIVE_HANDLE = "realDonaldTrump"

_TAG = re.compile(r"<[^>]+>")


@dataclass
class Post:
    id: str
    created_at: datetime
    text: str
    url: str


def _strip_html(content: str) -> str:
    text = _TAG.sub(" ", content or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_dt(raw) -> datetime | None:
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return raw


def fetch_posts(
    handle: str, since: datetime, *, source: str = "archive", replies: bool = False
) -> list[Post]:
    """Return posts by `handle` created at/after `since` (timezone-aware UTC)."""
    if source == "archive":
        return _fetch_from_archive(handle, since)
    if source == "truthbrush":
        return _fetch_from_truthbrush(handle, since, replies=replies)
    raise ValueError(f"unknown source: {source!r}")


def _fetch_from_archive(handle: str, since: datetime) -> list[Post]:
    if handle.lower() != ARCHIVE_HANDLE.lower():
        raise ValueError(
            f"the archive source only covers @{ARCHIVE_HANDLE}; "
            f"use --source truthbrush for @{handle}"
        )
    resp = requests.get(ARCHIVE_URL, timeout=60)
    resp.raise_for_status()
    posts: list[Post] = []
    for rec in resp.json():
        created = _parse_dt(rec.get("created_at"))
        if created is None or created < since:
            continue
        text = _strip_html(rec.get("content", ""))
        if not text:
            continue
        pid = str(rec.get("id"))
        url = rec.get("url") or f"https://truthsocial.com/@{ARCHIVE_HANDLE}/{pid}"
        posts.append(Post(id=pid, created_at=created, text=text, url=url))
    posts.sort(key=lambda p: p.created_at, reverse=True)
    return posts


def _fetch_from_truthbrush(handle: str, since: datetime, *, replies: bool) -> list[Post]:
    from truthbrush import Api  # imported lazily; only needed for this backend

    api = Api()  # reads TRUTHSOCIAL_USERNAME / TRUTHSOCIAL_PASSWORD from env
    posts: list[Post] = []
    for status in api.pull_statuses(handle, created_after=since, replies=replies):
        text = _strip_html(status.get("content", ""))
        if not text:
            continue
        pid = str(status.get("id"))
        url = status.get("url") or f"https://truthsocial.com/@{handle}/{pid}"
        posts.append(Post(id=pid, created_at=_parse_dt(status.get("created_at")),
                          text=text, url=url))
    return posts
