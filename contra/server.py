"""Dependency-free local HTTP API and web UI."""
from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from urllib.parse import urlparse, unquote

from .core import analyze, prepare
from .fixtures import AS_OF, DATASET_ID, STOCKS, dataset_hash, documents
from .store import connect, profiles, profile, update_profile, save_run, run, all_runs

WEB = Path(__file__).resolve().parent.parent / "web"


class Handler(BaseHTTPRequestHandler):
    server_version = "CONTRA/0.1"

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        data = json.dumps(body).encode() if content_type.startswith("application/json") else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size > 100_000:
            raise ValueError("Request body too large")
        try:
            return json.loads(self.rfile.read(size))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid JSON body") from exc

    def _error(self, status, code, message):
        self._send(status, {"error": code, "message": message})

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/health":
            with connect() as db:
                db.execute("SELECT 1")
            return self._send(200, {"status": "ok", "version": "0.1", "fixture_loaded": True})
        if path == "/v1/stocks":
            return self._send(200, {"dataset_id": DATASET_ID, "dataset_hash": dataset_hash(), "as_of": AS_OF,
                                    "stocks": [{"ticker": k, **{a: b for a, b in v.items() if a not in ("seed", "trend")},
                                                "mode": "SYNTHETIC"} for k, v in STOCKS.items()]})
        if path == "/v1/profiles":
            with connect() as db:
                result = profiles(db)
            return self._send(200, {"profiles": result})
        if path.startswith("/v1/profiles/") and path.endswith("/portfolio"):
            ident = path.split("/")[3]
            with connect() as db:
                item = profile(db, ident)
            return self._send(200, item) if item else self._error(404, "NOT_FOUND", "Unknown investor")
        if path.startswith("/v1/analyses/"):
            with connect() as db:
                item = run(db, path.split("/")[3])
            return self._send(200, item) if item else self._error(404, "NOT_FOUND", "Unknown run")
        if path.startswith("/v1/evidence/"):
            ident = path.split("/")[3]
            item = next((d for d in documents() if d["id"] == ident), None)
            return self._send(200, item) if item else self._error(404, "NOT_FOUND", "Unknown evidence")
        if path == "/v1/evaluations/summary":
            with connect() as db:
                runs = all_runs(db)
            latencies = sorted(r["metrics"]["wall_latency_ms"] for r in runs)
            validity = [r["metrics"]["citation_validity"] for r in runs if r["metrics"]["citation_validity"] is not None]
            summary = {"run_count": len(runs), "latency_ms": {"median": latencies[len(latencies)//2] if latencies else None,
                      "min": latencies[0] if latencies else None, "max": latencies[-1] if latencies else None},
                      "citation_validity_mean": round(sum(validity)/len(validity), 3) if validity else None,
                      "agent_overlap_count": sum(bool(r["metrics"]["agent_overlap"]) for r in runs),
                      "scenario_checks": {"conflict_fixture": "ALPHA.NS", "aligned_fixture": "GAMMA.NS",
                                          "missing_filing_fixture": "DELTA.NS"},
                      "note": "Measured run metrics and synthetic scenario fixtures; no return prediction accuracy is claimed."}
            return self._send(200, summary)
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
        path = urlparse(self.path).path
        if not path.startswith("/v1/profiles/"):
            return self._error(404, "NOT_FOUND", "Unknown route")
        try:
            changes = self._json()
            with connect() as db:
                item = update_profile(db, path.split("/")[3], changes)
            return self._send(200, item) if item else self._error(404, "NOT_FOUND", "Unknown investor")
        except ValueError as exc:
            return self._error(400, "BAD_INPUT", str(exc))


def main():
    with connect():
        pass
    host = os.environ.get("CONTRA_HOST", "127.0.0.1")
    port = int(os.environ.get("CONTRA_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"CONTRA synthetic demo: http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
