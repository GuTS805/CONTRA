"""Daily NSE/BSE prices from Yahoo Finance's public chart endpoint, plus user-supplied filings.

Yahoo's endpoint is unofficial and unlicensed for redistribution; reports label these
bars LIVE with their source URL so the provenance stays visible.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import re
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from . import store

LIVE_DATASET_ID = "yahoo_chart_daily_v1"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=6mo&interval=1d"
TICKER = re.compile(r"^[A-Z0-9][A-Z0-9&-]{0,19}\.(NS|BO)$")
SECTORS = ["Communication", "Consumer", "Energy", "Financials", "Healthcare", "Industrials",
           "Materials", "Real Estate", "Technology", "Utilities", "Other"]
CACHE_HOURS = 6
IST = timezone(timedelta(hours=5, minutes=30))
MARKET_CLOSE_IST = (15, 45)  # After the 15:30 close plus a short settlement buffer.

POSITIVE = {"improved", "improve", "improves", "improvement", "growth", "grew", "record", "strong", "stronger",
            "robust", "beat", "exceeded", "upgrade", "upgraded", "awarded", "won", "expansion", "expanded",
            "profitable", "profit", "surplus", "dividend", "buyback", "outperformed", "accelerated", "renewed",
            "approval", "approved", "commenced", "launched"}
NEGATIVE = {"loss", "losses", "decline", "declined", "declining", "weak", "weaker", "fell", "impairment",
            "default", "downgrade", "downgraded", "delay", "delayed", "narrowed", "pressure", "penalty",
            "litigation", "fraud", "resigned", "resignation", "shortfall", "writeoff", "slowdown", "disruption",
            "contracted", "deteriorated", "missed", "probe", "investigation", "suspended", "lawsuit"}


class UpstreamError(Exception):
    """The market data provider could not be reached or returned unusable data."""


def normalize_ticker(value) -> str:
    if not isinstance(value, str):
        raise ValueError("ticker is required")
    ticker = value.strip().upper()
    if not TICKER.match(ticker):
        raise ValueError("Use an NSE or BSE Yahoo symbol such as RELIANCE.NS or 500325.BO")
    return ticker


def _get_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (CONTRA research prototype)",
                                    "Accept": "application/json"})
    try:
        with urlopen(request, timeout=8) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            raise ValueError("Yahoo Finance has no data for this symbol") from exc
        raise UpstreamError(f"Yahoo Finance returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise UpstreamError("Yahoo Finance could not be reached") from exc


def parse_chart(ticker: str, payload: dict, now: datetime | None = None) -> tuple[str, list[dict]]:
    """Return the company name and completed daily bars from a chart response."""
    chart = payload.get("chart") or {}
    results = chart.get("result") or []
    if not results:
        description = (chart.get("error") or {}).get("description") or "No data found"
        raise ValueError(f"Yahoo Finance: {description}")
    result = results[0]
    meta = result.get("meta") or {}
    quote_rows = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    stamps, closes, volumes = result.get("timestamp") or [], quote_rows.get("close") or [], quote_rows.get("volume") or []
    now_ist = (now or datetime.now(timezone.utc)).astimezone(IST)
    session_open = (now_ist.hour, now_ist.minute) < MARKET_CLOSE_IST
    source = CHART_URL.format(symbol=quote(ticker))
    fetched = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    bars, seen = [], set()
    for stamp, close, volume in zip(stamps, closes, volumes):
        if not isinstance(stamp, (int, float)) or not isinstance(close, (int, float)) or \
                not isinstance(volume, (int, float)) or not math.isfinite(close) or close <= 0 or volume <= 0:
            continue
        trade_date = datetime.fromtimestamp(stamp, IST).date()
        # Today's bar is still forming until the session closes.
        if trade_date > now_ist.date() or (trade_date == now_ist.date() and session_open):
            continue
        if trade_date.isoformat() in seen:
            continue
        seen.add(trade_date.isoformat())
        bars.append({"id": f"BAR-{ticker}-{trade_date.isoformat()}", "ticker": ticker,
                     "trade_date": trade_date.isoformat(), "close": round(float(close), 4), "volume": int(volume),
                     "mode": "LIVE", "origin": "yahoo_finance_chart", "source_uri": source,
                     "timezone": meta.get("exchangeTimezoneName") or "Asia/Kolkata", "adjusted": False,
                     "currency": meta.get("currency"), "ingested_at": fetched})
    bars.sort(key=lambda bar: bar["trade_date"])
    if not bars:
        raise ValueError("Yahoo Finance returned no completed daily bars for this symbol")
    name = meta.get("longName") or meta.get("shortName") or ticker
    return str(name)[:120], bars


def fetch(ticker: str) -> tuple[str, list[dict]]:
    return parse_chart(ticker, _get_json(CHART_URL.format(symbol=quote(ticker))))


def bars(db, ticker: str, refresh: bool = True) -> tuple[list[dict], list[str]]:
    """Cached bars, refreshed when older than CACHE_HOURS. Falls back to the cache if Yahoo fails."""
    cached, fetched_at = store.cached_bars(db, ticker)
    stale = fetched_at is None or \
        datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at) > timedelta(hours=CACHE_HOURS)
    warnings = []
    if refresh and stale:
        try:
            _, fresh = fetch(ticker)
            store.cache_bars(db, ticker, fresh)
            return fresh, warnings
        except UpstreamError as exc:
            if cached is None:
                raise
            warnings.append(f"{exc}; using prices cached at {fetched_at[:16].replace('T', ' ')} UTC")
    if cached is None:
        raise UpstreamError("No cached prices for this symbol")
    return cached, warnings


def lexicon_tone(text: str) -> float:
    words = re.findall(r"[a-z]+", text.lower())
    positive = sum(word in POSITIVE for word in words)
    negative = sum(word in NEGATIVE for word in words)
    return round((positive - negative) / max(1, positive + negative), 3)


def make_document(ticker: str, body: dict, today: date | None = None) -> dict:
    """Validate a user-supplied filing excerpt and return a hashed, dated document."""
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    title, text = body.get("title"), body.get("excerpt")
    published, source_uri, tone = body.get("published_at"), body.get("source_uri") or "", body.get("tone")
    if not isinstance(title, str) or not 3 <= len(title.strip()) <= 120:
        raise ValueError("title must be 3-120 characters")
    if not isinstance(text, str) or not 20 <= len(text.strip()) <= 4000:
        raise ValueError("excerpt must be 20-4000 characters")
    try:
        published_date = date.fromisoformat(published) if isinstance(published, str) else None
    except ValueError:
        published_date = None
    if published_date is None:
        raise ValueError("published_at must be an ISO date")
    if published_date > (today or datetime.now(IST).date()):
        raise ValueError("published_at cannot be in the future")
    if not isinstance(source_uri, str) or len(source_uri) > 500 or \
            (source_uri and (urlparse(source_uri).scheme != "https" or not urlparse(source_uri).netloc)):
        raise ValueError("source_uri must be an https URL or empty")
    if tone is not None and (isinstance(tone, bool) or tone not in (-1, 0, 1)):
        raise ValueError("tone must be -1, 0, 1 or null for automatic")
    text = text.strip()
    base = ticker.split(".")[0]
    doc_id = f"E-{base}-{secrets.token_hex(3).upper()}"
    return {"id": doc_id, "document_id": "DOC-" + doc_id[2:], "ticker": ticker, "title": title.strip(),
            "published_at": published_date.isoformat(), "excerpt": text, "char_start": 0, "char_end": len(text),
            "tone": lexicon_tone(text) if tone is None else tone,
            "tone_source": "LEXICON_HEURISTIC" if tone is None else "USER_LABEL",
            "mode": "USER_UPLOADED", "source_type": "user_supplied_filing_excerpt",
            "source_uri": source_uri or f"user://{doc_id}",
            "source_hash": "sha256:" + sha256(text.encode()).hexdigest()}
