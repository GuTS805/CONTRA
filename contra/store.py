"""SQLite persistence for profiles and immutable analysis reports."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "contra.sqlite3"


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    target = Path(path or os.environ.get("CONTRA_DB", DEFAULT_DB))
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, investor_id TEXT NOT NULL, ticker TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS runs_investor_date ON runs(investor_id, created_at)")
    db.commit()
    seed_profiles(db)
    return db


def seed_profiles(db):
    now = datetime.now(timezone.utc).isoformat()
    positions = [{"ticker": "ALPHA.NS", "value": 15000}, {"ticker": "BETA.NS", "value": 25000},
                 {"ticker": "GAMMA.NS", "value": 20000}, {"ticker": "CASH", "value": 40000}]
    for ident, name, tier, cap in (("demo_conservative", "Conservative", "CONSERVATIVE", .10),
                                    ("demo_growth", "Growth", "GROWTH", .30)):
        profile = {"id": ident, "display_name": name, "risk_tier": tier,
                   "max_single_asset_weight": cap, "max_sector_weight": .5,
                   "investment_horizon": "LONG", "positions": positions,
                   "watchlist": ["ALPHA.NS", "BETA.NS", "GAMMA.NS", "DELTA.NS"],
                   "revision": 1, "updated_at": now, "mode": "SYNTHETIC"}
        db.execute("INSERT OR IGNORE INTO profiles(id,payload) VALUES (?,?)", (ident, json.dumps(profile)))
    db.commit()


def profiles(db):
    return [json.loads(row[0]) for row in db.execute("SELECT payload FROM profiles ORDER BY id")]


def profile(db, ident):
    row = db.execute("SELECT payload FROM profiles WHERE id=?", (ident,)).fetchone()
    return json.loads(row[0]) if row else None


def update_profile(db, ident, changes):
    current = profile(db, ident)
    if current is None:
        return None
    allowed = {"display_name", "risk_tier", "max_single_asset_weight", "max_sector_weight", "investment_horizon", "positions", "watchlist"}
    if not isinstance(changes, dict) or set(changes) - allowed:
        raise ValueError("Unknown or invalid profile fields")
    updated = {**current, **changes}
    for field in ("max_single_asset_weight", "max_sector_weight"):
        if not isinstance(updated[field], (float, int)) or not 0 < updated[field] <= 1:
            raise ValueError(f"{field} must be a fraction in (0,1]")
    if not isinstance(updated["positions"], list) or any(not isinstance(p, dict) or not isinstance(p.get("value"), (int, float)) or p["value"] < 0 or not isinstance(p.get("ticker"), str) for p in updated["positions"]):
        raise ValueError("positions must contain nonnegative valued assets")
    updated["revision"] = current["revision"] + 1
    updated["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.execute("UPDATE profiles SET payload=? WHERE id=?", (json.dumps(updated), ident))
    db.commit()
    return updated


def save_run(db, report):
    with db:
        db.execute("INSERT INTO runs(id,investor_id,ticker,created_at,payload) VALUES (?,?,?,?,?)",
                   (report["run_id"], report["investor_id"], report["ticker"], report["created_at"], json.dumps(report)))


def run(db, ident):
    row = db.execute("SELECT payload FROM runs WHERE id=?", (ident,)).fetchone()
    return json.loads(row[0]) if row else None


def all_runs(db):
    return [json.loads(row[0]) for row in db.execute("SELECT payload FROM runs ORDER BY created_at DESC")]
