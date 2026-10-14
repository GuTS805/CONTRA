"""Dependency-free HTTP API and web UI with per-user accounts."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import date
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from statistics import median
import sys
import traceback
from urllib.parse import urlparse, unquote, parse_qs

from . import auth, live
from .core import analyze, ask_filings, portfolio_insights, prepare
from .fixtures import AS_OF, DATASET_ID, STOCKS, bars_for, dataset_hash, documents
from .evaluation import scenario_matrix, benchmark_fixed
from .llm import configured as llm_configured
from .settings import load_env
from . import store
from .store import RunIntegrityError, RevisionConflict, baseline_profiles

WEB = Path(__file__).resolve().parent.parent / "web"
LOOPBACK = {"127.0.0.1", "localhost"}
MAX_SECURITIES = 20
MAX_DOCUMENTS = 200


@contextmanager
def database():
    db = store.connect()
    try:
        yield db
    finally:
        db.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "CONTRA/0.2"

    # Response helpers ---------------------------------------------------------

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        data = json.dumps(body, allow_nan=False).encode() if content_type.startswith("application/json") else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if self.server.secure_cookies:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        for cookie in getattr(self, "_set_cookies", []):
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status, code, message):
        self._send(status, {"error": code, "message": message})

    def _json(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if size < 0:
            raise ValueError("Invalid Content-Length")
        if size > 100_000:
            raise ValueError("Request body too large")
        def reject_constant(value):
            raise ValueError(f"Invalid JSON number: {value}")
        try:
            body = json.loads(self.rfile.read(size), parse_constant=reject_constant)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid JSON body") from exc
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        return body

    # Request trust, identity and limits ----------------------------------------

    def _allowed_hosts(self):
        port = self.server.server_port
        return {f"{name}:{port}" for name in LOOPBACK} | self.server.public_hosts

    def _trusted_request(self, mutation=False):
        """Reject foreign Host headers (DNS rebinding) and cross-origin or non-JSON mutations."""
        allowed = self._allowed_hosts()
        if self.headers.get("Host", "") not in allowed:
            self._error(403, "INVALID_HOST", "This server does not accept that Host header")
            return False
        if mutation:
            origin = self.headers.get("Origin")
            origins = {f"http://{item}" for item in allowed if item.split(":")[0] in LOOPBACK} | \
                      {f"https://{item}" for item in self.server.public_hosts}
            if origin is not None and origin not in origins:
                self._error(403, "INVALID_ORIGIN", "Cross-origin changes are not allowed")
                return False
            if self.command != "DELETE" and \
                    self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self._error(415, "UNSUPPORTED_MEDIA_TYPE", "JSON Content-Type is required")
                return False
        return True

    def _client_ip(self):
        if self.server.trust_proxy and self.headers.get("X-Forwarded-For"):
            # The hosting proxy appends the address it saw; earlier entries are client-supplied.
            return self.headers["X-Forwarded-For"].split(",")[-1].strip()
        return self.client_address[0]

    def _limited(self, key, limit, window):
        if auth.limiter.allow(key, limit, window):
            return False
        self._error(429, "RATE_LIMITED", "Too many requests; wait a few minutes and try again")
        return True

    def _token(self):
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        morsel = cookie.get(auth.SESSION_COOKIE)
        return morsel.value if morsel else None

    def _set_session_cookie(self, token, max_age):
        secure = "; Secure" if self.server.secure_cookies else ""
        self._set_cookies = [f"{auth.SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{secure}"]

    def _require_user(self, db):
        user = auth.user_for_token(db, self._token())
        if user is None:
            self._error(401, "AUTH_REQUIRED", "Log in or continue as a guest to use CONTRA")
        return user

    # Dispatch -----------------------------------------------------------------

    def _dispatch(self, mutation, handler):
        self._set_cookies = []
        path = unquote(urlparse(self.path).path)
        if path == "/health" and self.command == "GET":
            return self._health()
        if not self._trusted_request(mutation=mutation):
            return
        try:
            return handler(path)
        except RunIntegrityError as exc:
            return self._error(500, "DATA_INTEGRITY", str(exc))
        except live.UpstreamError as exc:
            return self._error(502, "UPSTREAM_UNAVAILABLE", str(exc))
        except RevisionConflict as exc:
            return self._error(409, "REVISION_CONFLICT", str(exc))
        except ValueError as exc:
            return self._error(400, "BAD_INPUT", str(exc))
        except Exception:
            traceback.print_exc(file=sys.stderr)
            return self._error(500, "INTERNAL", "Unexpected server error")

    def do_GET(self):
        self._dispatch(False, self._get)

    def do_POST(self):
        self._dispatch(True, self._post)

    def do_PUT(self):
        self._dispatch(True, self._put)

    def do_DELETE(self):
        self._dispatch(True, self._delete)

    def _health(self):
        with database() as db:
            db.execute("SELECT 1")
        return self._send(200, {"status": "ok", "version": "0.2", "fixture_loaded": True,
                                "llm_enabled": llm_configured()})

    # GET ----------------------------------------------------------------------

    def _get(self, path):
        static = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}
        if path in static:
            filename = static[path]
            mime = "text/html" if filename.endswith("html") else "text/javascript" if filename.endswith("js") else "text/css"
            return self._send(200, (WEB / filename).read_bytes(), mime + "; charset=utf-8")
        if path.startswith("/analysis/") or path in ("/portfolio", "/evidence", "/evaluation"):
            return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
        if not path.startswith("/v1/"):
            return self._error(404, "NOT_FOUND", "Unknown route")
        params = parse_qs(urlparse(self.path).query)
        parts = path.split("/")
        with database() as db:
            user = self._require_user(db)
            if user is None:
                return
            owner = user["id"]
            if path == "/v1/auth/me":
                return self._send(200, user)
            if path == "/v1/stocks":
                return self._send(200, self._catalog(db, owner))
            if path == "/v1/profiles":
                return self._send(200, {"profiles": store.profiles(db, owner)})
            if len(parts) == 5 and parts[2] == "profiles" and parts[4] in ("portfolio", "insights"):
                item = store.profile(db, parts[3], owner)
                if item is None:
                    return self._error(404, "NOT_FOUND", "Unknown investor")
                if parts[4] == "portfolio":
                    return self._send(200, item)
                sectors = {ticker: info["sector"] for ticker, info in store.universe(db, owner).items()}
                return self._send(200, portfolio_insights(item, sectors))
            if path == "/v1/analyses":
                investor = params.get("investor_id", [None])[0]
                try:
                    limit = int(params.get("limit", [20])[0])
                    offset = int(params.get("offset", [0])[0])
                except ValueError:
                    return self._error(400, "BAD_INPUT", "limit and offset must be integers")
                if not 1 <= limit <= 100 or not 0 <= offset <= 9_223_372_036_854_775_807:
                    return self._error(400, "BAD_INPUT", "limit must be 1-100 and offset must fit a nonnegative SQLite integer")
                reports, total = store.recent_runs(db, investor, limit, offset, owner)
                summaries = [{"run_id": report["run_id"], "ticker": report["ticker"],
                              "investor_id": report["investor_id"], "created_at": report["created_at"],
                              "as_of": report["as_of"], "state": report["synthesis"]["state"],
                              "action": (report.get("recommendation") or {}).get("action"),
                              "data_mode": report["data_mode"]} for report in reports]
                return self._send(200, {"runs": summaries, "count": len(summaries), "total": total,
                                        "limit": limit, "offset": offset, "has_more": offset + len(summaries) < total})
            if len(parts) >= 4 and parts[2] == "analyses":
                report = store.run(db, parts[3], owner)
                if report is None:
                    return self._error(404, "NOT_FOUND", "Unknown run")
                if len(parts) == 4:
                    return self._send(200, report)
                if len(parts) == 5 and parts[4] == "ask":
                    try:
                        return self._send(200, ask_filings(report, params.get("q", [None])[0]))
                    except LookupError as exc:
                        return self._error(409, "LEGACY_RUN", str(exc))
                if len(parts) == 6 and parts[4] == "evidence":
                    evidence_id = parts[5]
                    if evidence_id == report["investor_snapshot"]["id"]:
                        return self._send(200, report["investor_snapshot"])
                    candidates = report["market_snapshot"]["bars"] + report["evidence"] + \
                        report["market_snapshot"].get("documents", [])
                    item = next((entry for entry in candidates if entry["id"] == evidence_id), None)
                    return self._send(200, item) if item else self._error(404, "NOT_FOUND", "Evidence is not in this run")
                return self._error(404, "NOT_FOUND", "Unknown route")
            if path == "/v1/evidence":
                ticker, as_of = params.get("ticker", [None])[0], params.get("as_of", [None])[0]
                if ticker is not None and ticker not in store.universe(db, owner):
                    return self._error(404, "NOT_FOUND", "Unknown ticker")
                if as_of is not None:
                    try:
                        date.fromisoformat(as_of)
                    except ValueError:
                        return self._error(400, "BAD_INPUT", "Invalid as_of date")
                library = store.user_documents(db, owner) + documents()
                items = [doc for doc in library if (ticker is None or doc["ticker"] == ticker)
                         and (as_of is None or doc["published_at"] <= as_of)]
                return self._send(200, {"documents": items, "count": len(items)})
            if len(parts) == 4 and parts[2] == "evidence":
                ident = parts[3]
                item = next((d for d in store.user_documents(db, owner) + documents() if d["id"] == ident), None)
                if item is None and ident.startswith("BAR-"):
                    ticker = next((t for t in STOCKS if ident.startswith(f"BAR-{t}-")), None)
                    item = next((b for b in bars_for(ticker) if b["id"] == ident), None) if ticker else None
                return self._send(200, item) if item else self._error(404, "NOT_FOUND", "Unknown evidence")
            if path == "/v1/evaluations/summary":
                runs = store.all_runs(db, owner)
            elif path == "/v1/evaluations/benchmark":
                if self._limited("bench:" + owner, 10, 600):
                    return
                return self._send(200, asyncio.run(benchmark_fixed(baseline_profiles()[0])))
            else:
                return self._error(404, "NOT_FOUND", "Unknown route")
        conservative, growth = baseline_profiles()
        scenario = asyncio.run(scenario_matrix(conservative, growth))
        latencies = sorted(r["metrics"]["wall_latency_ms"] for r in runs)
        validity = [r["metrics"]["citation_validity"] for r in runs if r["metrics"]["citation_validity"] is not None]
        return self._send(200, {"run_count": len(runs), "latency_ms": {"median": median(latencies) if latencies else None,
                                "min": latencies[0] if latencies else None, "max": latencies[-1] if latencies else None},
                                "citation_validity_mean": round(sum(validity) / len(validity), 3) if validity else None,
                                "agent_overlap_count": sum(bool(r["metrics"]["agent_overlap"]) for r in runs),
                                "scenario_checks": scenario,
                                "note": "Measured run metrics and synthetic scenario fixtures; no return prediction accuracy is claimed."})

    def _catalog(self, db, owner):
        stocks = [{"ticker": ticker, "name": spec["name"], "sector": spec["sector"], "scenario": spec["scenario"],
                   "mode": "SYNTHETIC", "dataset_id": DATASET_ID, "first_date": bars_for(ticker)[0]["trade_date"],
                   "last_date": bars_for(ticker)[-1]["trade_date"]} for ticker, spec in STOCKS.items()]
        for security in store.securities(db, owner):
            cached, fetched_at = store.cached_bars(db, security["ticker"])
            stocks.append({**security, "mode": "LIVE", "dataset_id": live.LIVE_DATASET_ID,
                           "first_date": cached[0]["trade_date"] if cached else None,
                           "last_date": cached[-1]["trade_date"] if cached else None,
                           "prices_fetched_at": fetched_at,
                           "document_count": len(store.user_documents(db, owner, security["ticker"]))})
        return {"dataset_id": DATASET_ID, "dataset_hash": dataset_hash(), "as_of": AS_OF,
                "analysis_mode": "LLM_WITH_FALLBACK" if llm_configured() else "DETERMINISTIC_FALLBACK",
                "sectors": live.SECTORS, "live_provider": "Yahoo Finance chart API (unofficial, daily, unadjusted close)",
                "stocks": stocks}

    # POST ---------------------------------------------------------------------

    def _post(self, path):
        if path.startswith("/v1/auth/"):
            return self._auth(path)
        body = self._json()
        with database() as db:
            user = self._require_user(db)
            if user is None:
                return
            owner = user["id"]
            if path == "/v1/analyses":
                return self._analysis(db, owner, body)
            if path == "/v1/securities":
                ticker = live.normalize_ticker(body.get("ticker"))
                sector = body.get("sector")
                if sector not in live.SECTORS:
                    raise ValueError("sector must be one of: " + ", ".join(live.SECTORS))
                if ticker in STOCKS:
                    raise ValueError("That symbol is reserved for a synthetic scenario")
                known = {item["ticker"] for item in store.securities(db, owner)}
                if ticker not in known and len(known) >= MAX_SECURITIES:
                    raise ValueError(f"You can track up to {MAX_SECURITIES} live symbols")
                if self._limited("security:" + owner, 30, 3600):
                    return
                name, bars = live.fetch(ticker)
                store.cache_bars(db, ticker, bars)
                store.add_security(db, owner, ticker, name, sector)
                return self._send(201, {"ticker": ticker, "name": name, "sector": sector, "mode": "LIVE",
                                        "first_date": bars[0]["trade_date"], "last_date": bars[-1]["trade_date"],
                                        "bar_count": len(bars)})
            if path == "/v1/documents":
                ticker = body.get("ticker")
                if ticker not in {item["ticker"] for item in store.securities(db, owner)}:
                    raise ValueError("Add this live symbol before attaching filings; synthetic fixtures are frozen")
                if len(store.user_documents(db, owner)) >= MAX_DOCUMENTS:
                    raise ValueError(f"You can store up to {MAX_DOCUMENTS} filing excerpts")
                document = live.make_document(ticker, body)
                store.save_document(db, owner, document)
                return self._send(201, document)
        return self._error(404, "NOT_FOUND", "Unknown route")

    def _auth(self, path):
        ip = self._client_ip()
        with database() as db:
            if path == "/v1/auth/logout":
                auth.end_session(db, self._token())
                secure = "; Secure" if self.server.secure_cookies else ""
                self._set_cookies = [f"{auth.SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0{secure}"]
                return self._send(200, {"status": "logged_out"})
            if path == "/v1/auth/guest":
                if self._limited("guest:" + ip, 20, 3600):
                    return
                user = auth.guest(db)
            elif path in ("/v1/auth/signup", "/v1/auth/login"):
                body = self._json()
                if path == "/v1/auth/signup":
                    if self._limited("signup:" + ip, 10, 3600):
                        return
                    user = auth.signup(db, body.get("username"), body.get("password"))
                else:
                    if self._limited("login:" + ip, 10, 600):
                        return
                    user = auth.login(db, body.get("username"), body.get("password"))
                    if user is None:
                        return self._error(401, "INVALID_CREDENTIALS", "Username or password is incorrect")
            else:
                return self._error(404, "NOT_FOUND", "Unknown route")
            token, max_age = auth.start_session(db, user["id"])
        self._set_session_cookie(token, max_age)
        return self._send(201 if path != "/v1/auth/login" else 200, user)

    def _analysis(self, db, owner, body):
        ticker, investor = body.get("ticker"), body.get("investor_id")
        if not isinstance(ticker, str) or not isinstance(investor, str):
            raise ValueError("ticker and investor_id are required")
        catalog = store.universe(db, owner)
        if ticker not in catalog:
            return self._error(404, "NOT_FOUND", "Unknown ticker; add the live symbol first")
        dataset_id = DATASET_ID if catalog[ticker]["mode"] == "SYNTHETIC" else live.LIVE_DATASET_ID
        if body.get("dataset_id", dataset_id) != dataset_id:
            return self._error(409, "DATASET_MISMATCH", "Unknown dataset version for this ticker")
        person = store.profile(db, investor, owner)
        if person is None:
            return self._error(404, "NOT_FOUND", "Unknown investor")
        if self._limited("analysis:" + owner, 30, 600):
            return
        as_of = body.get("as_of")
        if as_of is not None and not isinstance(as_of, str):
            raise ValueError("as_of must be an ISO date")
        warnings = []
        if dataset_id == DATASET_ID:
            snapshot = prepare(ticker, as_of or AS_OF)
        else:
            bars, warnings = live.bars(db, ticker)
            snapshot = prepare(ticker, as_of or bars[-1]["trade_date"], bars,
                               store.user_documents(db, owner, ticker), live.LIVE_DATASET_ID, "LIVE")
        sectors = {key: info["sector"] for key, info in catalog.items()}
        report = asyncio.run(analyze(ticker, person, snapshot=snapshot, sectors=sectors, warnings=warnings))
        store.save_run(db, report, owner)
        return self._send(201, report)

    # PUT / DELETE ---------------------------------------------------------------

    def _put(self, path):
        parts = path.split("/")
        if len(parts) != 4 or parts[2] != "profiles":
            return self._error(404, "NOT_FOUND", "Unknown route")
        changes = self._json()
        with database() as db:
            user = self._require_user(db)
            if user is None:
                return
            item = store.update_profile(db, parts[3], changes, user["id"], store.universe(db, user["id"]))
        return self._send(200, item) if item else self._error(404, "NOT_FOUND", "Unknown investor")

    def _delete(self, path):
        parts = path.split("/")
        if len(parts) != 4 or parts[2] not in ("securities", "documents"):
            return self._error(404, "NOT_FOUND", "Unknown route")
        with database() as db:
            user = self._require_user(db)
            if user is None:
                return
            owner = user["id"]
            if parts[2] == "documents":
                removed = store.delete_document(db, owner, parts[3])
            else:
                if any(position["ticker"] == parts[3] for item in store.profiles(db, owner)
                       for position in item["positions"]):
                    return self._error(409, "IN_USE", "Remove this symbol from your holdings before deleting it")
                removed = store.remove_security(db, owner, parts[3])
        return self._send(200, {"deleted": parts[3]}) if removed else self._error(404, "NOT_FOUND", "Nothing to delete")

    def log_message(self, format, *args):
        # Keep request lines but never echo query strings, which may contain user questions.
        sys.stderr.write("%s - %s\n" % (self.address_string(), (format % args).split("?", 1)[0]))


def main():
    loaded = load_env()
    store.connect().close()
    host = os.environ.get("CONTRA_HOST", "127.0.0.1")
    public = os.environ.get("CONTRA_PUBLIC") == "1"
    if host not in LOOPBACK and not public:
        raise SystemExit("Binding beyond loopback requires CONTRA_PUBLIC=1 and CONTRA_ALLOWED_HOSTS")
    public_hosts = {name.strip().lower() for name in os.environ.get("CONTRA_ALLOWED_HOSTS", "").split(",") if name.strip()}
    if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
        public_hosts.add(os.environ["RENDER_EXTERNAL_HOSTNAME"].lower())
    if public and not public_hosts:
        raise SystemExit("CONTRA_PUBLIC=1 needs CONTRA_ALLOWED_HOSTS (for example contra.onrender.com)")
    port = int(os.environ.get("CONTRA_PORT") or os.environ.get("PORT") or "8000")
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.public_hosts = public_hosts if public else set()
    server.trust_proxy = public
    server.secure_cookies = public
    print(f"CONTRA: http://{'localhost' if host in LOOPBACK else host}:{port}"
          + (f" (public hosts: {', '.join(sorted(public_hosts))})" if public else ""), flush=True)
    if loaded:
        print(f"Loaded settings from .env: {', '.join(sorted(loaded))}", flush=True)
    print("Model reasoning: " + ("enabled" if llm_configured() else
          "off (set CONTRA_LLM=1 and OPENAI_API_KEY in .env to enable)"), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
