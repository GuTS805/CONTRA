"""Provisional, combined-exchange institutional activity. Never ticker ownership."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from threading import Lock
from time import monotonic
from urllib.request import Request, urlopen

SOURCE = "https://www.nseindia.com/reports/fii-dii"
ENDPOINT = "https://www.nseindia.com/api/fiidiiTradeReact"
SCOPE = "NSE, BSE and MSEI capital market segment"
MAX_AGE_DAYS = 4  # Calendar-day product policy, not an exchange freshness guarantee.
_lock = Lock()
_last_attempt = {}


def checksum(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse(payload, observed_at=None, mode="LIVE"):
    """Reject incomplete dates, duplicate categories and inconsistent money values."""
    if mode not in ("LIVE", "SYNTHETIC") or not isinstance(payload, list) or len(payload) != 2:
        raise ValueError("Exactly one FII/FPI and one DII row required")
    groups, dates = {}, set()
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError("Institutional rows must be objects")
        category = row.get("category")
        if category not in ("FII/FPI", "DII") or category in groups:
            raise ValueError("Invalid or duplicate institutional category")
        try:
            day = datetime.strptime(row["date"], "%d-%b-%Y").date().isoformat()
        except (KeyError, TypeError) as exc:
            raise ValueError("Invalid institutional trade date") from exc
        dates.add(day)
        values = []
        for key in ("buyValue", "sellValue", "netValue"):
            try:
                value = Decimal(str(row[key]).replace(",", ""))
            except (InvalidOperation, KeyError) as exc:
                raise ValueError("Invalid flow value") from exc
            if not value.is_finite() or abs(value) > Decimal("1000000000"):
                raise ValueError("Invalid flow value")
            values.append(value)
        buy, sell, net = values
        if buy < 0 or sell < 0 or abs(buy - sell - net) > Decimal("0.02"):
            raise ValueError("Flow buy minus sell does not match net")
        groups[category] = dict(zip(("buy", "sell", "net"), map(float, values)))
    if len(dates) != 1:
        raise ValueError("FII and DII trade dates must match")
    observed_at = observed_at or datetime.now(timezone.utc).isoformat()
    observed = datetime.fromisoformat(observed_at)
    if observed.tzinfo is None:
        raise ValueError("Observation time must have a timezone")
    day = dates.pop()
    if mode == "LIVE" and day > observed.astimezone(timezone.utc).date().isoformat():
        raise ValueError("Future institutional trade date")
    record = {"trade_date": day, "groups": groups, "units": "INR crore", "scope": SCOPE,
              "mode": mode, "provisional": True, "source_uri": SOURCE if mode == "LIVE" else "fixture://institutional-flows-v1",
              "observed_at": observed_at, "raw_rows": payload}
    record["source_hash"] = "sha256:" + checksum(record)
    record["id"] = "FLOW-" + day + "-" + record["source_hash"][-12:]
    return record


def validate(record, mode):
    rebuilt = parse(record["raw_rows"], record["observed_at"], mode)
    if rebuilt != record:
        raise ValueError("Institutional flow provenance or checksum mismatch")


def fixture(as_of):
    from .fixtures import AS_OF
    if as_of < AS_OF:
        return []
    day = date.fromisoformat(AS_OF).strftime("%d-%b-%Y")
    return [parse([{"category": "FII/FPI", "date": day, "buyValue": "8200", "sellValue": "10000", "netValue": "-1800"},
                  {"category": "DII", "date": day, "buyValue": "10400", "sellValue": "8000", "netValue": "2400"}],
                  AS_OF + "T18:00:00+05:30", "SYNTHETIC")]


def fetch():
    request = Request(ENDPOINT, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": SOURCE})
    with urlopen(request, timeout=8) as response:
        raw = response.read(100001)
    if len(raw) > 100000:
        raise ValueError("Oversized flow response")
    return parse(json.loads(raw))


def history(db, as_of):
    """Cache successful observations; a provider outage never becomes a zero flow."""
    date.fromisoformat(as_of)
    warnings = []
    with _lock:
        db.execute("CREATE TABLE IF NOT EXISTS institutional_flows (id TEXT PRIMARY KEY, trade_date TEXT NOT NULL, payload TEXT NOT NULL)")
        key = db.execute("PRAGMA database_list").fetchone()[2]
        rows = db.execute("SELECT payload FROM institutional_flows ORDER BY trade_date DESC, id").fetchall()
        records = [json.loads(row[0]) for row in rows]
        recent = max((datetime.fromisoformat(r["observed_at"]) for r in records), default=None)
        now = datetime.now(timezone.utc)
        if (recent is None or (now - recent).total_seconds() >= 3600) and monotonic() - _last_attempt.get(key, -1e10) >= 300:
            _last_attempt[key] = monotonic()
            try:
                record = fetch()
                db.execute("INSERT OR IGNORE INTO institutional_flows VALUES (?, ?, ?)",
                           (record["id"], record["trade_date"], json.dumps(record)))
                db.commit()
                records.append(record)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                warnings.append("NSE institutional flows could not be refreshed; eligible cached observations only. " + type(exc).__name__)
    eligible = [r for r in records if r["trade_date"] <= as_of]
    latest = max(eligible, key=lambda r: (r["trade_date"], r["observed_at"]), default=None)
    return ([latest] if latest else []), warnings


def signal(snapshot):
    records = snapshot.get("institutional_flows", [])
    base = {"status": "UNAVAILABLE", "label": "UNKNOWN", "value": None, "evidence_confidence": None,
            "evidence_ids": [], "reason": "No eligible FII/DII observation for this date.",
            "warning": "Market-wide provisional activity, not buying in this stock. Historical views are reconstructed, not point-in-time backtests."}
    if not records:
        return base
    record = max(records, key=lambda r: (r["trade_date"], r["observed_at"]))
    age = (date.fromisoformat(snapshot["as_of"]) - date.fromisoformat(record["trade_date"])).days
    base.update(evidence_ids=[record["id"]], trade_date=record["trade_date"], age_days=age, mode=record["mode"])
    if age < 0 or age > MAX_AGE_DAYS:
        base["reason"] = f"Last flow observation is {age} calendar days old; maximum permitted age is {MAX_AGE_DAYS}."
        return base
    fii, dii = (record["groups"][key]["net"] for key in ("FII/FPI", "DII"))
    label = "DIVERGENT" if fii * dii < 0 else "NET_BUYING" if fii + dii > 0 else "NET_SELLING" if fii + dii < 0 else "BALANCED"
    base.update(status="OK", label=label, value=round(fii + dii, 2), fii_net=fii, dii_net=dii,
                reason=f"FII/FPI {fii:+,.2f} and DII {dii:+,.2f} INR crore on {record['trade_date']}. "
                       + ("Foreign and domestic institutions took opposite sides." if label == "DIVERGENT" else "Net is purchases minus sales.")
                       + (" Synthetic scenario." if record["mode"] == "SYNTHETIC" else " Provisional exchange data."))
    return base
