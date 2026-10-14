"""Validate and stage user-supplied market snapshots without activating them."""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from urllib.parse import urlparse

MAX_BYTES = 10_000_000
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")


def _date(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date") from exc


def _text(value, label, maximum=500):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be nonempty text of at most {maximum} characters")
    return value


def validate(payload):
    """Return a normalized immutable snapshot or raise a precise input error."""
    if not isinstance(payload, dict) or set(payload) != {"dataset_id", "as_of", "license_note", "stocks", "bars", "documents"}:
        raise ValueError("Expected dataset_id, as_of, license_note, stocks, bars and documents")
    ident = payload["dataset_id"]
    if not isinstance(ident, str) or not ID_RE.fullmatch(ident) or ident == "contra_synthetic_v1":
        raise ValueError("Invalid or reserved dataset_id")
    as_of = _date(payload["as_of"], "as_of")
    _text(payload["license_note"], "license_note", 1000)
    stocks = payload["stocks"]
    bars = payload["bars"]
    docs = payload["documents"]
    if not isinstance(stocks, list) or not 1 <= len(stocks) <= 100:
        raise ValueError("stocks must contain 1-100 entries")
    if not isinstance(bars, list) or not 1 <= len(bars) <= 100_000:
        raise ValueError("bars must contain 1-100000 entries")
    if not isinstance(docs, list) or len(docs) > 10_000:
        raise ValueError("documents must contain at most 10000 entries")
    tickers = set()
    for stock in stocks:
        if not isinstance(stock, dict) or set(stock) != {"ticker", "name", "sector"}:
            raise ValueError("Each stock needs ticker, name and sector")
        ticker = stock["ticker"]
        if not isinstance(ticker, str) or not ID_RE.fullmatch(ticker) or ticker in tickers:
            raise ValueError("Invalid or duplicate stock ticker")
        tickers.add(ticker)
        _text(stock["name"], "stock name")
        _text(stock["sector"], "stock sector")
    seen_bars = set()
    latest = {}
    for bar in bars:
        required = {"ticker", "trade_date", "close", "volume", "source_uri", "adjusted", "timezone"}
        if not isinstance(bar, dict) or set(bar) != required or bar["ticker"] not in tickers:
            raise ValueError("Invalid bar fields or unknown ticker")
        day = _date(bar["trade_date"], "trade_date")
        if day > as_of or (bar["ticker"], day) in seen_bars:
            raise ValueError("Future or duplicate market bar")
        seen_bars.add((bar["ticker"], day))
        latest[bar["ticker"]] = max(day, latest.get(bar["ticker"], day))
        for field in ("close", "volume"):
            value = bar[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"bar {field} must be finite and positive")
        if type(bar["adjusted"]) is not bool:
            raise ValueError("adjusted must be boolean")
        _text(bar["timezone"], "timezone", 80)
        _source(bar["source_uri"])
    if set(latest) != tickers:
        raise ValueError("Every stock needs at least one bar")
    seen_docs = set()
    for doc in docs:
        required = {"id", "ticker", "title", "published_at", "excerpt", "source_uri", "source_hash", "char_start", "char_end"}
        if not isinstance(doc, dict) or set(doc) != required or doc["ticker"] not in tickers:
            raise ValueError("Invalid document fields or unknown ticker")
        doc_id = doc["id"]
        if not isinstance(doc_id, str) or not ID_RE.fullmatch(doc_id) or doc_id in seen_docs:
            raise ValueError("Invalid or duplicate document ID")
        seen_docs.add(doc_id)
        _date(doc["published_at"], "published_at")
        _text(doc["title"], "document title")
        excerpt = _text(doc["excerpt"], "excerpt", 20_000)
        if type(doc["char_start"]) is not int or type(doc["char_end"]) is not int or doc["char_start"] < 0 or doc["char_end"] - doc["char_start"] != len(excerpt):
            raise ValueError("Excerpt offsets must match excerpt length")
        _source(doc["source_uri"])
        if doc["source_hash"] != "sha256:" + sha256(excerpt.encode("utf-8")).hexdigest():
            raise ValueError("Document source_hash does not match excerpt")
    return {**payload, "data_mode": "IMPORTED_UNVERIFIED"}


def _source(uri):
    if not isinstance(uri, str) or len(uri) > 2000:
        raise ValueError("source_uri must be an HTTPS URL")
    parsed = urlparse(uri)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("source_uri must be an HTTPS URL without embedded credentials")


def stage(source: Path, destination: Path):
    if source.stat().st_size > MAX_BYTES:
        raise ValueError("Import exceeds 10 MB limit")
    payload = json.loads(source.read_text(encoding="utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON number")))
    validated = validate(payload)
    canonical = json.dumps(validated, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    checksum = sha256(canonical).hexdigest()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{validated['dataset_id']}-{checksum[:16]}.json"
    if target.exists():
        if target.read_bytes() != canonical:
            raise ValueError("Existing staged snapshot differs")
    else:
        with target.open("xb") as output:
            output.write(canonical)
    return {"path": str(target), "sha256": checksum, "data_mode": validated["data_mode"],
            "stocks": len(validated["stocks"]), "bars": len(validated["bars"]), "documents": len(validated["documents"])}


def main():
    parser = argparse.ArgumentParser(description="Validate and stage an unverified data snapshot; analyses remain synthetic")
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", type=Path, default=Path("data/imports"))
    args = parser.parse_args()
    try:
        print(json.dumps(stage(args.source, args.destination), indent=2))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Import rejected: {exc}\n")


if __name__ == "__main__":
    main()
