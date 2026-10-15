"""SQLite persistence for accounts, per-user profiles, filings and immutable analysis reports."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
from threading import Lock

from .fixtures import STOCKS
from .core import digest

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "contra.sqlite3"
# Owner for in-process use without accounts (tests and command-line scripts).
LOCAL_OWNER = "local"
_MIGRATED: set[str] = set()
_MIGRATION_LOCK = Lock()


class RevisionConflict(Exception):
    """The caller edited an out-of-date investor profile."""


class RunIntegrityError(Exception):
    """A stored report no longer matches its creation-time checksum."""


def verify_run(report):
    expected = report.get("report_hash")
    if expected is not None and expected != digest({key: value for key, value in report.items() if key != "report_hash"}):
        raise RunIntegrityError("Saved report checksum does not match its contents")
    if expected is not None or str(report.get("method_version", "")).startswith("rules-"):
        market = report.get("market_snapshot", {})
        snapshot_hash = digest({"dataset": report.get("dataset_id"), "ticker": report.get("ticker"),
                                "as_of": report.get("as_of"), "bars": market.get("bars"),
                                "documents": market.get("documents"),
                                **({"institutional_flows": market["institutional_flows"]} if "institutional_flows" in market else {})})
        if snapshot_hash != report.get("market_snapshot_hash") or \
                digest({"snapshot": snapshot_hash, "profile": report.get("investor_snapshot")}) != report.get("run_context_hash"):
            raise RunIntegrityError("Saved market or investor snapshot checksum does not match")
    return report


def _migrate(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, investor_id TEXT NOT NULL, ticker TEXT NOT NULL,
            created_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT, is_guest INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS user_profiles (owner_id TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY (owner_id, id));
        CREATE TABLE IF NOT EXISTS user_securities (owner_id TEXT NOT NULL, ticker TEXT NOT NULL, name TEXT NOT NULL,
            sector TEXT NOT NULL, added_at TEXT NOT NULL, PRIMARY KEY (owner_id, ticker));
        CREATE TABLE IF NOT EXISTS user_documents (owner_id TEXT NOT NULL, id TEXT NOT NULL, ticker TEXT NOT NULL,
            payload TEXT NOT NULL, PRIMARY KEY (owner_id, id));
        CREATE TABLE IF NOT EXISTS market_bars (ticker TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS embedding_cache (key TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
    if "owner_id" not in columns:
        # Runs saved before accounts existed have no owner and are not shown to any user.
        db.execute("ALTER TABLE runs ADD COLUMN owner_id TEXT")
    db.execute("CREATE INDEX IF NOT EXISTS runs_owner_date ON runs(owner_id, created_at)")
    db.commit()


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    target = Path(path or os.environ.get("CONTRA_DB", DEFAULT_DB))
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, timeout=10)
    db.row_factory = sqlite3.Row
    key = str(target.resolve())
    if key not in _MIGRATED:
        # Concurrent first connections (for example three agent threads) must not migrate twice at once.
        with _MIGRATION_LOCK:
            if key not in _MIGRATED:
                _migrate(db)
                seed_profiles(db, LOCAL_OWNER)
                _MIGRATED.add(key)
    return db


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def baseline_profiles(updated_at: str | None = None) -> list[dict]:
    now = updated_at or "2026-10-13T00:00:00+00:00"
    holder = [{"ticker": "ALPHA.NS", "value": 15000}, {"ticker": "BETA.NS", "value": 25000},
              {"ticker": "GAMMA.NS", "value": 5000}, {"ticker": "CASH", "value": 55000}]
    # A newer investor: mostly cash, no ALPHA position, moderate caps.
    starter = [{"ticker": "BETA.NS", "value": 10000}, {"ticker": "GAMMA.NS", "value": 5000},
               {"ticker": "CASH", "value": 85000}]
    result = []
    for ident, name, tier, cap, sector_cap, horizon, positions in (
            ("demo_conservative", "Conservative", "CONSERVATIVE", .10, .5, "LONG", holder),
            ("demo_growth", "Growth", "GROWTH", .30, .5, "LONG", holder),
            ("demo_starter", "Starter", "BALANCED", .15, .4, "MEDIUM", starter)):
        profile = {"id": ident, "display_name": name, "risk_tier": tier,
                   "max_single_asset_weight": cap, "max_sector_weight": sector_cap,
                   "investment_horizon": horizon, "positions": [dict(position) for position in positions],
                   "watchlist": ["ALPHA.NS", "BETA.NS", "GAMMA.NS", "DELTA.NS"],
                   "revision": 1, "updated_at": now, "mode": "SYNTHETIC"}
        result.append(profile)
    return result


def seed_profiles(db, owner_id=LOCAL_OWNER):
    for profile in baseline_profiles(now_iso()):
        db.execute("INSERT OR IGNORE INTO user_profiles(owner_id,id,payload) VALUES (?,?,?)",
                   (owner_id, profile["id"], json.dumps(profile)))
    db.commit()


# Accounts -----------------------------------------------------------------

def insert_user(db, user_id, username, password_hash, is_guest=False):
    try:
        with db:
            db.execute("INSERT INTO users(id,username,password_hash,is_guest,created_at) VALUES (?,?,?,?,?)",
                       (user_id, username, password_hash, int(is_guest), now_iso()))
    except sqlite3.IntegrityError as exc:
        raise ValueError("That username is already taken") from exc
    seed_profiles(db, user_id)
    return {"id": user_id, "username": username, "is_guest": is_guest}


def user_by_name(db, username):
    row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return dict(row) if row else None


def save_session(db, token_hash, user_id, expires_at):
    with db:
        db.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso(),))
        db.execute("INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES (?,?,?,?)",
                   (token_hash, user_id, expires_at, now_iso()))


def session_user(db, token_hash):
    row = db.execute("SELECT users.id, users.username, users.is_guest FROM sessions JOIN users ON users.id=sessions.user_id "
                     "WHERE token_hash=? AND expires_at > ?", (token_hash, now_iso())).fetchone()
    return {"id": row["id"], "username": row["username"], "is_guest": bool(row["is_guest"])} if row else None


def delete_session(db, token_hash):
    with db:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))


# Securities and filings ------------------------------------------------------

def securities(db, owner_id=LOCAL_OWNER):
    return [dict(row) for row in db.execute(
        "SELECT ticker,name,sector,added_at FROM user_securities WHERE owner_id=? ORDER BY ticker", (owner_id,))]


def add_security(db, owner_id, ticker, name, sector):
    with db:
        db.execute("INSERT OR REPLACE INTO user_securities(owner_id,ticker,name,sector,added_at) VALUES (?,?,?,?,?)",
                   (owner_id, ticker, name, sector, now_iso()))


def remove_security(db, owner_id, ticker):
    with db:
        removed = db.execute("DELETE FROM user_securities WHERE owner_id=? AND ticker=?", (owner_id, ticker)).rowcount
        db.execute("DELETE FROM user_documents WHERE owner_id=? AND ticker=?", (owner_id, ticker))
    return bool(removed)


def universe(db, owner_id=LOCAL_OWNER) -> dict:
    """Every ticker this owner may analyze or hold, with its sector and data mode."""
    items = {ticker: {"name": spec["name"], "sector": spec["sector"], "mode": "SYNTHETIC"}
             for ticker, spec in STOCKS.items()}
    for row in securities(db, owner_id):
        items[row["ticker"]] = {"name": row["name"], "sector": row["sector"], "mode": "LIVE"}
    return items


def user_documents(db, owner_id=LOCAL_OWNER, ticker=None):
    query = "SELECT payload FROM user_documents WHERE owner_id=?" + (" AND ticker=?" if ticker else "")
    args = (owner_id, ticker) if ticker else (owner_id,)
    docs = [json.loads(row[0]) for row in db.execute(query, args)]
    return sorted(docs, key=lambda doc: (doc["published_at"], doc["id"]), reverse=True)


def save_document(db, owner_id, document):
    with db:
        db.execute("INSERT INTO user_documents(owner_id,id,ticker,payload) VALUES (?,?,?,?)",
                   (owner_id, document["id"], document["ticker"], json.dumps(document, allow_nan=False)))


def delete_document(db, owner_id, ident):
    with db:
        return db.execute("DELETE FROM user_documents WHERE owner_id=? AND id=?", (owner_id, ident)).rowcount > 0


def cached_bars(db, ticker):
    row = db.execute("SELECT payload, fetched_at FROM market_bars WHERE ticker=?", (ticker,)).fetchone()
    return (json.loads(row[0]), row[1]) if row else (None, None)


def cache_bars(db, ticker, bars):
    with db:
        db.execute("INSERT OR REPLACE INTO market_bars(ticker,payload,fetched_at) VALUES (?,?,?)",
                   (ticker, json.dumps(bars, allow_nan=False), now_iso()))


class ModelCache:
    """Durable key/value store for model answers or embedding vectors, keyed by a content hash."""

    def __init__(self, table="llm_cache"):
        if table not in ("llm_cache", "embedding_cache"):
            raise ValueError("unknown cache table")
        self.table = table

    def get(self, key):
        db = connect()
        try:
            row = db.execute(f"SELECT payload FROM {self.table} WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            db.close()

    def put(self, key, answer):
        db = connect()
        try:
            with db:
                db.execute(f"INSERT OR REPLACE INTO {self.table}(key,payload,created_at) VALUES (?,?,?)",
                           (key, json.dumps(answer), now_iso()))
        finally:
            db.close()

    def all(self):
        db = connect()
        try:
            return {row[0]: json.loads(row[1]) for row in db.execute(f"SELECT key, payload FROM {self.table}")}
        finally:
            db.close()


# Profiles -------------------------------------------------------------------

def profiles(db, owner_id=LOCAL_OWNER):
    return [json.loads(row[0]) for row in db.execute(
        "SELECT payload FROM user_profiles WHERE owner_id=? ORDER BY id", (owner_id,))]


def profile(db, ident, owner_id=LOCAL_OWNER):
    row = db.execute("SELECT payload FROM user_profiles WHERE owner_id=? AND id=?", (owner_id, ident)).fetchone()
    return json.loads(row[0]) if row else None


def update_profile(db, ident, changes, owner_id=LOCAL_OWNER, tickers=None):
    """Validate and save a new profile revision. `tickers` lists every holdable ticker."""
    known = set(tickers if tickers is not None else STOCKS)
    row = db.execute("SELECT payload FROM user_profiles WHERE owner_id=? AND id=?", (owner_id, ident)).fetchone()
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
    if not isinstance(updated["watchlist"], list) or any(not isinstance(ticker, str) or ticker not in known for ticker in updated["watchlist"]) or \
            len(updated["watchlist"]) != len(set(updated["watchlist"])):
        raise ValueError("watchlist must contain unique known tickers")
    for field in ("max_single_asset_weight", "max_sector_weight"):
        if isinstance(updated[field], bool) or not isinstance(updated[field], (float, int)) or not 0 < updated[field] <= 1 or not math.isfinite(updated[field]):
            raise ValueError(f"{field} must be a fraction in (0,1]")
    if not isinstance(updated["positions"], list) or len(updated["positions"]) > 60 or \
            any(not isinstance(p, dict) or isinstance(p.get("value"), bool) or
            not isinstance(p.get("value"), (int, float)) or p["value"] < 0 or
            p["value"] > 1_000_000_000_000 or not math.isfinite(p["value"]) or
            not isinstance(p.get("ticker"), str) or
            p["ticker"] not in known and p["ticker"] != "CASH" for p in updated["positions"]):
        raise ValueError("positions must contain nonnegative values for known tickers or CASH")
    if len({p["ticker"] for p in updated["positions"]}) != len(updated["positions"]):
        raise ValueError("positions must have unique tickers")
    updated["positions"] = [{"ticker": p["ticker"], "value": p["value"]} for p in updated["positions"]]
    updated["revision"] = current["revision"] + 1
    updated["updated_at"] = now_iso()
    cursor = db.execute("UPDATE user_profiles SET payload=? WHERE owner_id=? AND id=? AND payload=?",
                        (json.dumps(updated, allow_nan=False), owner_id, ident, row[0]))
    if cursor.rowcount != 1:
        db.rollback()
        raise RevisionConflict("Profile changed during save; reload before retrying")
    db.commit()
    return updated


# Runs -----------------------------------------------------------------------

def save_run(db, report, owner_id=LOCAL_OWNER):
    verify_run(report)
    with db:
        db.execute("INSERT INTO runs(id,investor_id,ticker,created_at,payload,owner_id) VALUES (?,?,?,?,?,?)",
                   (report["run_id"], report["investor_id"], report["ticker"], report["created_at"],
                    json.dumps(report, allow_nan=False), owner_id))


def run(db, ident, owner_id=LOCAL_OWNER):
    row = db.execute("SELECT payload FROM runs WHERE id=? AND owner_id=?", (ident, owner_id)).fetchone()
    return verify_run(json.loads(row[0])) if row else None


def all_runs(db, owner_id=LOCAL_OWNER):
    return [verify_run(json.loads(row[0])) for row in db.execute(
        "SELECT payload FROM runs WHERE owner_id=? ORDER BY created_at DESC", (owner_id,))]


def recent_runs(db, investor_id=None, limit=20, offset=0, owner_id=LOCAL_OWNER):
    where = " WHERE owner_id=?" + (" AND investor_id=?" if investor_id else "")
    args = (owner_id, investor_id) if investor_id else (owner_id,)
    total = db.execute("SELECT COUNT(*) FROM runs" + where, args).fetchone()[0]
    rows = db.execute("SELECT payload FROM runs" + where + " ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                      (*args, limit, offset))
    return [verify_run(json.loads(row[0])) for row in rows], total
