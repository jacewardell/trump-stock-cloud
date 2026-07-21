"""Email the daily mention summary (with chart attached) when there are any.

Reads output/<DATE>.json. If it has no company mentions, sends nothing and
returns False. Otherwise emails a summary + the day's PNG chart via Gmail SMTP.

Env (see .env): GMAIL_USER, GMAIL_APP_PASSWORD (Gmail app password),
NOTIFY_TO (recipient; defaults to GMAIL_USER).
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
SITE_URL = "https://jacewardell.github.io/trump-stock-cloud/"


def _summary_lines(companies: list[dict]) -> list[str]:
    lines = []
    for c in companies:
        idx = ", ".join(c.get("indices") or [])
        lines.append(f"{c['count']:>3}x  {c['symbol']:<6} {c['name']}"
                     + (f"  [{idx}]" if idx else ""))
        for p in c.get("posts", []):
            when = (p.get("created_at") or "").replace("T", " ")[:16]
            excerpt = (p.get("excerpt") or "").strip()
            lines.append(f"        - {when}  {excerpt}")
            if p.get("url"):
                lines.append(f"          {p['url']}")
    return lines


def build_message(data: dict, sender: str, recipient: str,
                  png_path: Path | None) -> EmailMessage:
    date_str = data["date"]
    handle = data.get("handle", "realDonaldTrump")
    companies = data["companies"]
    post_count = data.get("post_count", 0)
    top = companies[0]

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = (f"Trump stock mentions {date_str}: "
                      f"{top['symbol']} x{top['count']}"
                      + (f" (+{len(companies) - 1} more)" if len(companies) > 1 else ""))

    body = [
        f"@{handle} mentioned {len(companies)} "
        f"{'company' if len(companies) == 1 else 'companies'} "
        f"on {date_str} ({post_count} posts scanned).",
        "",
        *_summary_lines(companies),
        "",
        f"Full chart + history: {SITE_URL}",
    ]
    msg.set_content("\n".join(body))

    if png_path and png_path.exists():
        msg.add_attachment(png_path.read_bytes(), maintype="image",
                           subtype="png", filename=png_path.name)
    return msg


def _smtp_creds() -> tuple[str, str, str] | None:
    """Return (user, password, recipient) or None if not configured."""
    user = os.getenv("GMAIL_USER")
    password = os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("NOTIFY_TO") or user
    if not user or not password:
        return None
    return user, password, recipient


def _send(msg: EmailMessage, user: str, password: str) -> None:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(user, password.replace(" ", ""))
        smtp.send_message(msg)


def send_alert_email(subject: str, body: str) -> bool:
    """Send a plain-text real-time alert. Returns True if sent, False if SMTP
    is not configured. Used by the poller, separate from the daily digest."""
    creds = _smtp_creds()
    if not creds:
        print("notify: GMAIL_USER / GMAIL_APP_PASSWORD not set; alert skipped")
        return False
    user, password, recipient = creds
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)
    _send(msg, user, password)
    print(f"notify: alert emailed to {recipient}")
    return True


def send_mention_email(date_str: str) -> bool:
    """Returns True if an email was sent, False if skipped (no mentions)."""
    json_path = OUTPUT_DIR / f"{date_str}.json"
    if not json_path.exists():
        print(f"notify: {json_path} not found; skipping")
        return False

    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not data.get("companies"):
        print(f"notify: no mentions for {date_str}; no email sent")
        return False

    creds = _smtp_creds()
    if not creds:
        print("notify: GMAIL_USER / GMAIL_APP_PASSWORD not set; skipping email")
        return False
    user, password, recipient = creds

    msg = build_message(data, user, recipient, OUTPUT_DIR / f"{date_str}.png")
    _send(msg, user, password)
    print(f"notify: emailed {len(data['companies'])} mentions to {recipient}")
    return True


def main():
    load_dotenv()
    p = argparse.ArgumentParser(description="Email the daily mention summary")
    p.add_argument("--date", help="Date label (YYYY-MM-DD, ET); default today")
    args = p.parse_args()
    date_str = args.date or datetime.now(ET).strftime("%Y-%m-%d")
    send_mention_email(date_str)


if __name__ == "__main__":
    main()
