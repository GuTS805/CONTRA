"""Dependency-free local HTTP API and web UI."""
from __future__ import annotations

import asyncio
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from statistics import median
from urllib.parse import urlparse, unquote, parse_qs

from .core import analyze, prepare
from .fixtures import AS_OF, DATASET_ID, STOCKS, bars_for, dataset_hash, documents
from .evaluation import scenario_matrix, benchmark_fixed
from .llm import configured as llm_configured
from .store import RunIntegrityError, RevisionConflict, baseline_profiles, connect, profiles, profile, update_profile, save_run, run, all_runs, recent_runs

WEB = Path(__file__).resolve().parent.parent / "web"


class Handler(BaseHTTPRequestHandler):
    server_version = "CONTRA/0.1"

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        data = json.dumps(body, allow_nan=False).encode() if content_type.startswith("application/json") else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def _json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size < 0:
            raise ValueError("Invalid Content-Length")
        if size > 100_000:
            raise ValueError("Request body too large")
        def reject_constant(value):
            raise ValueError(f"Invalid JSON number: {value}")
        try:
            return json.loads(self.rfile.read(size), parse_constant=reject_constant)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid JSON body") from exc

    def _error(self, status, code, message):
        self._send(status, {"error": code, "message": message})

    def _trusted_request(self, mutation=False):
        """Keep the unauthenticated demo on its own loopback origin."""
        host = self.headers.get("Host", "")
        expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if host not in expected:
            self._error(403, "INVALID_HOST", "This local demo accepts only its loopback host")
            return False
        if mutation:
            origin = self.headers.get("Origin")
            if origin is not None and origin not in {f"http://{item}" for item in expected}:
                self._error(403, "INVALID_ORIGIN", "Cross-origin changes are not allowed")
                return False
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self._error(415, "UNSUPPORTED_MEDIA_TYPE", "JSON Content-Type is required")
                return False
        return True

    def do_GET(self):
        if not self._trusted_request():
            return
        try:
            return self._do_GET()
        except RunIntegrityError as exc:
            return self._error(500, "DATA_INTEGRITY", str(exc))

    def _do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/health":
            with connect() as db:
                db.execute("SELECT 1")
            return self._send(200, {"status": "ok", "version": "0.1", "fixture_loaded": True,
                                    "llm_enabled": llm_configured()})
        if path == "/v1/stocks":
            return self._send(200, {"dataset_id": DATASET_ID, "dataset_hash": dataset_hash(), "as_of": AS_OF,
                                    "analysis_mode": "LLM_WITH_FALLBACK" if llm_configured() else "DETERMINISTIC_FALLBACK",
                                    "stocks": [{"ticker": k, **{a: b for a, b in v.items() if a not in ("seed", "trend")},
                                                "mode": "SYNTHETIC", "first_date": bars_for(k)[0]["trade_date"],
                                                "last_date": bars_for(k)[-1]["trade_date"]} for k, v in STOCKS.items()]})
        if path == "/v1/profiles":
            with connect() as db:
                result = profiles(db)
            return self._send(200, {"profiles": result})
        if path.startswith("/v1/profiles/") and path.endswith("/portfolio") and len(path.split("/")) == 5:
            ident = path.split("/")[3]
            with connect() as db:
                item = profile(db, ident)
            return self._send(200, item) if item else self._error(404, "NOT_FOUND", "Unknown investor")
        if path == "/v1/analyses":
            params = parse_qs(urlparse(self.path).query)
            investor = params.get("investor_id", [None])[0]
            try:
                limit = int(params.get("limit", [20])[0])
                offset = int(params.get("offset", [0])[0])
            except ValueError:
                return self._error(400, "BAD_INPUT", "limit and offset must be integers")
            if not 1 <= limit <= 100 or not 0 <= offset <= 9_223_372_036_854_775_807:
                return self._error(400, "BAD_INPUT", "limit must be 1-100 and offset must fit a nonnegative SQLite integer")
            with connect() as db:
                reports, total = recent_runs(db, investor, limit, offset)
            summaries = [{"run_id": report["run_id"], "ticker": report["ticker"],
                          "investor_id": report["investor_id"], "created_at": report["created_at"],
                          "as_of": report["as_of"], "state": report["synthesis"]["state"],
                          "data_mode": report["data_mode"]} for report in reports]
            return self._send(200, {"runs": summaries, "count": len(summaries), "total": total,
                                    "limit": limit, "offset": offset, "has_more": offset + len(summaries) < total})
        if path.startswith("/v1/analyses/") and "/evidence/" in path:
            parts = path.split("/")
            if len(parts) != 6 or parts[4] != "evidence":
                return self._error(404, "NOT_FOUND", "Unknown route")
            with connect() as db:
                report = run(db, parts[3])
            if report is None:
                return self._error(404, "NOT_FOUND", "Unknown run")
            evidence_id = parts[5]
            candidates = report["market_snapshot"]["bars"] + report["evidence"] + report["market_snapshot"].get("documents", [])
            if evidence_id == report["investor_snapshot"]["id"]:
                return self._send(200, report["investor_snapshot"])
            item = next((entry for entry in candidates if entry["id"] == evidence_id), None)
            return self._send(200, item) if item else self._error(404, "NOT_FOUND", "Evidence is not in this run")
        if path.startswith("/v1/analyses/"):
            if len(path.split("/")) != 4:
                return self._error(404, "NOT_FOUND", "Unknown route")
            with connect() as db:
                item = run(db, path.split("/")[3])
            return self._send(200, item) if item else self._error(404, "NOT_FOUND", "Unknown run")
        if path == "/v1/evidence":
            params = parse_qs(urlparse(self.path).query)
            ticker = params.get("ticker", [None])[0]
            as_of = params.get("as_of", [None])[0]
            if ticker is not None and ticker not in STOCKS:
                return self._error(404, "NOT_FOUND", "Unknown ticker")
            if as_of is not None:
                try:
                    date.fromisoformat(as_of)
                except ValueError:
                    return self._error(400, "BAD_INPUT", "Invalid as_of date")
            items = [doc for doc in documents() if (ticker is None or doc["ticker"] == ticker)
                     and (as_of is None or doc["published_at"] <= as_of)]
            return self._send(200, {"documents": items, "count": len(items)})
        if path.startswith("/v1/evidence/"):
            if len(path.split("/")) != 4:
                return self._error(404, "NOT_FOUND", "Unknown route")
            ident = path.split("/")[3]
            item = next((d for d in documents() if d["id"] == ident), None)
            if item is None and ident.startswith("BAR-"):
                for ticker in STOCKS:
                    if ident.startswith(f"BAR-{ticker}-"):
                        item = next((b for b in bars_for(ticker) if b["id"] == ident), None)
                        break
            return self._send(200, item) if item else self._error(404, "NOT_FOUND", "Unknown evidence")
        if path == "/v1/evaluations/summary":
            with connect() as db:
                runs = all_runs(db)
            conservative, growth = baseline_profiles()
            scenario = asyncio.run(scenario_matrix(conservative, growth))
            latencies = sorted(r["metrics"]["wall_latency_ms"] for r in runs)
            validity = [r["metrics"]["citation_validity"] for r in runs if r["metrics"]["citation_validity"] is not None]
            summary = {"run_count": len(runs), "latency_ms": {"median": median(latencies) if latencies else None,
                      "min": latencies[0] if latencies else None, "max": latencies[-1] if latencies else None},
                      "citation_validity_mean": round(sum(validity)/len(validity), 3) if validity else None,
                      "agent_overlap_count": sum(bool(r["metrics"]["agent_overlap"]) for r in runs),
                      "scenario_checks": scenario,
                      "note": "Measured run metrics and synthetic scenario fixtures; no return prediction accuracy is claimed."}
            return self._send(200, summary)
        if path == "/v1/evaluations/benchmark":
            conservative = baseline_profiles()[0]
            return self._send(200, asyncio.run(benchmark_fixed(conservative)))
        static = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
        filename = static.get(path)
        if filename:
            file = WEB / filename
            mime = "text/html" if filename.endswith("html") else "text/javascript" if filename.endswith("js") else "text/css"
            return self._send(200, file.read_bytes(), mime + "; charset=utf-8")
        if path.startswith("/analysis/") or path in ("/portfolio", "/evidence", "/evaluation"):
            return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
        return self._error(404, "NOT_FOUND", "Unknown route")

    def do_POST(self):
        if not self._trusted_request(mutation=True):
            return
        if urlparse(self.path).path != "/v1/analyses":
            return self._error(404, "NOT_FOUND", "Unknown route")
        try:
            body = self._json()
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            ticker, investor = body.get("ticker"), body.get("investor_id")
            if not isinstance(ticker, str) or not isinstance(investor, str):
                raise ValueError("ticker and investor_id are required")
            if body.get("dataset_id", DATASET_ID) != DATASET_ID:
                return self._error(409, "DATASET_MISMATCH", "Unknown dataset version")
            if ticker not in STOCKS:
                return self._error(404, "NOT_FOUND", "Unknown ticker")
            with connect() as db:
                person = profile(db, investor)
                if person is None:
                    return self._error(404, "NOT_FOUND", "Unknown investor")
                as_of = body.get("as_of", AS_OF)
                if not isinstance(as_of, str):
                    raise ValueError("as_of must be an ISO date")
                prepare(ticker, as_of)
                report = asyncio.run(analyze(ticker, person, as_of))
                save_run(db, report)
            return self._send(201, report)
        except ValueError as exc:
            return self._error(400, "BAD_INPUT", str(exc))

    def do_PUT(self):
        if not self._trusted_request(mutation=True):
            return
        path = urlparse(self.path).path
        if not path.startswith("/v1/profiles/") or len(path.split("/")) != 4:
            return self._error(404, "NOT_FOUND", "Unknown route")
        try:
            changes = self._json()
            with connect() as db:
                item = update_profile(db, path.split("/")[3], changes)
            return self._send(200, item) if item else self._error(404, "NOT_FOUND", "Unknown investor")
        except RevisionConflict as exc:
            return self._error(409, "REVISION_CONFLICT", str(exc))
        except ValueError as exc:
            return self._error(400, "BAD_INPUT", str(exc))


def main():
    with connect():
        pass
    host = os.environ.get("CONTRA_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("The unauthenticated demo may bind only to 127.0.0.1 or localhost")
    port = int(os.environ.get("CONTRA_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"CONTRA synthetic demo: http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
