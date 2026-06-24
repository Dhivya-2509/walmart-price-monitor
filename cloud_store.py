"""
cloud_store.py - JSONBin.io cloud storage for prices_db.json
Used by webapp_cloud.py (Render) and monitor.py / webapp.py (local Windows)

Set env vars:
  JSONBIN_KEY  — your JSONBin Master Key
  JSONBIN_ID   — your JSONBin Bin ID (created on first run)
"""

import json
import os
import urllib.request
from pathlib import Path

JSONBIN_API = "https://api.jsonbin.io/v3/b"
LOCAL_DB = Path(__file__).parent / "prices_db.json"


def _cfg():
    return os.environ.get("JSONBIN_KEY", ""), os.environ.get("JSONBIN_ID", "")


def load_db() -> dict:
    """Load prices from JSONBin cloud (with local file fallback)."""
    key, bin_id = _cfg()
    if key and bin_id:
        try:
            req = urllib.request.Request(f"{JSONBIN_API}/{bin_id}/latest")
            req.add_header("X-Master-Key", key)
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read()).get("record", {})
        except Exception:
            pass
    if LOCAL_DB.exists():
        with open(LOCAL_DB, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_db(db: dict) -> None:
    """Save prices to JSONBin cloud and local file."""
    key, bin_id = _cfg()
    if key and bin_id:
        try:
            payload = json.dumps(db).encode()
            req = urllib.request.Request(
                f"{JSONBIN_API}/{bin_id}", data=payload, method="PUT"
            )
            req.add_header("X-Master-Key", key)
            req.add_header("Content-Type", "application/json")
            urllib.request.urlopen(req, timeout=15)
        except Exception:
            pass  # Don't fail if cloud is unavailable

    # Always save locally too
    try:
        with open(LOCAL_DB, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2)
    except Exception:
        pass


def create_bin(initial_data: dict) -> str:
    """Create a new JSONBin and return its ID. Call once during setup."""
    key, _ = _cfg()
    if not key:
        raise ValueError("JSONBIN_KEY env var not set")
    payload = json.dumps(initial_data).encode()
    req = urllib.request.Request(JSONBIN_API, data=payload, method="POST")
    req.add_header("X-Master-Key", key)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Bin-Name", "walmart-price-monitor")
    req.add_header("X-Bin-Private", "true")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["metadata"]["id"]
