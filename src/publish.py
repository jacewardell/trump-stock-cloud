"""Build output/manifest.json — a compact index of all daily results that the
static GitHub Pages site (index.html) reads to render charts and trends."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
ET = ZoneInfo("America/New_York")


def build_manifest(out_dir: Path = OUTPUT_DIR) -> Path:
    days = []
    handle = "realDonaldTrump"
    for p in sorted(out_dir.glob("*.json")):
        if p.name == "manifest.json":
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if "date" not in d:
            continue
        handle = d.get("handle") or handle
        days.append({
            "date": d["date"],
            "post_count": d.get("post_count", 0),
            "companies": [
                {"symbol": c["symbol"], "name": c["name"], "count": c["count"]}
                for c in d.get("companies", [])
            ],
        })
    days.sort(key=lambda x: x["date"])
    manifest = {
        "updated": datetime.now(ET).isoformat(timespec="seconds"),
        "handle": handle,
        "days": days,
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(f"Wrote {build_manifest()}")
