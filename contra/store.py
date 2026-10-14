"""SQLite persistence for profiles and immutable analysis reports."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3

from .fixtures import STOCKS
from .core import digest

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "contra.sqlite3"


class RevisionConflict(Exception):
    """The caller edited an out-of-date investor profile."""


class RunIntegrityError(Exception):
    """A stored report no longer matches its creation-time checksum."""


def verify_run(report):
    expected = report.get("report_hash")
    if expected is not None and expected != digest({key: value for key, value in report.items() if key != "report_hash"}):
        raise RunIntegrityError("Saved report checksum does not match its contents")
    if expected is not None or report.get("method_version") == "rules-1.1":
        market = report.get("market_snapshot", {})
        snapshot_hash = digest({"dataset": report.get("dataset_id"), "ticker": report.get("ticker"),
                                "as_of": report.get("as_of"), "bars": market.get("bars"),
                                "documents": market.get("documents")})
        if snapshot_hash != report.get("market_snapshot_hash") or \
                digest({"snapshot": snapshot_hash, "profile": report.get("investor_snapshot")}) != report.get("run_context_hash"):
            raise RunIntegrityError("Saved market or investor snapshot checksum does not match")
    return report


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


def baseline_profiles(updated_at: str | None = None) -> list[dict]:
    now = updated_at or "2026-10-13T00:00:00+00:00"
    positions = [{"ticker": "ALPHA.NS", "value": 15000}, {"ticker": "BETA.NS", "value": 25000},
                 {"ticker": "GAMMA.NS", "value": 5000}, {"ticker": "CASH", "value": 55000}]
    result = []
    for ident, name, tier, cap in (("demo_conservative", "Conservative", "CONSERVATIVE", .10),
                                    ("demo_growth", "Growth", "GROWTH", .30)):
        profile = {"id": ident, "display_name": name, "risk_tier": tier,
                   "max_single_asset_weight": cap, "max_sector_weight": .5,
                   "investment_horizon": "LONG", "positions": [dict(position) for position in positions],
                   "watchlist": ["ALPHA.NS", "BETA.NS", "GAMMA.NS", "DELTA.NS"],
                   "revision": 1, "updated_at": now, "mode": "SYNTHETIC"}
        result.append(profile)
    return result


def seed_profiles(db):
    for profile in baseline_profiles(datetime.now(timezone.utc).isoformat()):
        ident = profile["id"]
        db.execute("INSERT OR IGNORE INTO profiles(id,payload) VALUES (?,?)", (ident, json.dumps(profile)))
    db.commit()


def profiles(db):
    return [json.loads(row[0]) for row in db.execute("SELECT payload FROM profiles ORDER BY id")]


def profile(db, ident):
    row = db.execute("SELECT payload FROM profiles WHERE id=?", (ident,)).fetchone()
    return json.loads(row[0]) if row else None


def update_profile(db, ident, changes):
    row = db.execute("SELECT payload FROM profiles WHERE id=?", (ident,)).fetchone()
    if row is None:
        return None
    current = json.loads(row[0])
    if not isinstance(changes, dict):
        raise ValueError("Profile update must be a JSON object")
    expected_revision = changes.get("expected_revision")
    if expected_revision is not None:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ValueError("expected_revision must be an integer")
        if expected_revision != current["revision"]:
            raise RevisionConflict("Profile changed since it was loaded; reload before saving")
    changes = {key: value for key, value in changes.items() if key != "expected_revision"}
    if not changes:
        raise ValueError("At least one profile field must be supplied")
    allowed = {"display_name", "risk_tier", "max_single_asset_weight", "max_sector_weight", "investment_horizon", "positions", "watchlist"}
    if set(changes) - allowed:
        raise ValueError("Unknown or invalid profile fields")
    updated = {**current, **changes}
    if not isinstance(updated["display_name"], str) or not 1 <= len(updated["display_name"].strip()) <= 80:
        raise ValueError("display_name must be 1-80 characters")
    if not isinstance(updated["risk_tier"], str) or updated["risk_tier"] not in {"CONSERVATIVE", "BALANCED", "GROWTH"}:
        raise ValueError("risk_tier is invalid")
    if not isinstance(updated["investment_horizon"], str) or updated["investment_horizon"] not in {"SHORT", "MEDIUM", "LONG"}:
        raise ValueError("investment_horizon is invalid")
    if not isinstance(updated["watchlist"], list) or any(not isinstance(ticker, str) or ticker not in STOCKS for ticker in updated["watchlist"]) or \
            len(updated["watchlist"]) != len(set(updated["watchlist"])):
        raise ValueError("watchlist must contain unique known synthetic tickers")
    for field in ("max_single_asset_weight", "max_sector_weight"):
        if isinstance(updated[field], bool) or not isinstance(updated[field], (float, int)) or not 0 < updated[field] <= 1 or not math.isfinite(updated[field]):
            raise ValueError(f"{field} must be a fraction in (0,1]")
    if not isinstance(updated["positions"], list) or any(not isinstance(p, dict) or isinstance(p.get("value"), bool) or
            not isinstance(p.get("value"), (int, float)) or p["value"] < 0 or
            p["value"] > 1_000_000_000_000 or not math.isfinite(p["value"]) or
            not isinstance(p.get("ticker"), str) or
            p["ticker"] not in STOCKS and p["ticker"] != "CASH" for p in updated["positions"]):
        raise ValueError("positions must contain nonnegative valued assets")
    if len({p["ticker"] for p in updated["positions"]}) != len(updated["positions"]):
        raise ValueError("positions must have unique tickers")
    updated["revision"] = current["revision"] + 1
    updated["updated_at"] = datetime.now(timezone.utc).isoformat()
    cursor = db.execute("UPDATE profiles SET payload=? WHERE id=? AND payload=?",
                        (json.dumps(updated, allow_nan=False), ident, row[0]))
    if cursor.rowcount != 1:
        db.rollback()
        raise RevisionConflict("Profile changed during save; reload before retrying")
    db.commit()
    return updated


def save_run(db, report):
    verify_run(report)
    with db:
        db.execute("INSERT INTO runs(id,investor_id,ticker,created_at,payload) VALUES (?,?,?,?,?)",
                   (report["run_id"], report["investor_id"], report["ticker"], report["created_at"], json.dumps(report, allow_nan=False)))


def run(db, ident):
    row = db.execute("SELECT payload FROM runs WHERE id=?", (ident,)).fetchone()
    return verify_run(json.loads(row[0])) if row else None


def all_runs(db):
    return [verify_run(json.loads(row[0])) for row in db.execute("SELECT payload FROM runs ORDER BY created_at DESC")]


def recent_runs(db, investor_id=None, limit=20, offset=0):
    where = " WHERE investor_id=?" if investor_id else ""
    args = (investor_id,) if investor_id else ()
    total = db.execute("SELECT COUNT(*) FROM runs" + where, args).fetchone()[0]
    rows = db.execute("SELECT payload FROM runs" + where + " ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                      (*args, limit, offset))
    return [verify_run(json.loads(row[0])) for row in rows], total
