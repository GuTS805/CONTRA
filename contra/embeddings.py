"""OpenAI text embeddings for filing search, with caching and daily limits.

Vectors are cached by a hash of model, dimensions and text. The server installs a
durable store and preloads the shipped warm-up file, so the demo filings and common
questions are answered without new calls.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from threading import Lock
from urllib.request import Request, urlopen

from . import llm

API_URL = "https://api.openai.com/v1/embeddings"
MODEL = "text-embedding-3-small"
DIMENSIONS = 256
CACHE_SIZE = 5000
_cache: OrderedDict = OrderedDict()
_usage = {"day": None, "calls": 0, "owners": {}}
_lock = Lock()
# Optional durable cache installed by the server: get(key) -> list | None and put(key, vector).
persistent_cache = None


class EmbeddingUnavailable(RuntimeError):
    """Embeddings are disabled, over today's limit, or the provider failed."""


def available() -> bool:
    return llm.configured() and os.environ.get("CONTRA_EMBEDDINGS", "1") != "0"


def _limit(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def key_for(text: str) -> str:
    return sha256(json.dumps([MODEL, DIMENSIONS, text]).encode()).hexdigest()


def reset_state() -> None:
    with _lock:
        _cache.clear()
        _usage.update(day=None, calls=0, owners={})


def usage() -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    with _lock:
        if _usage["day"] != today:
            _usage.update(day=today, calls=0, owners={})
        return {"day": today, "calls": _usage["calls"], "limit": _limit("CONTRA_EMBED_DAILY_LIMIT", 300),
                "account_limit": _limit("CONTRA_EMBED_ACCOUNT_DAILY_LIMIT", 40), "cached_vectors": len(_cache)}


def preload(entries: dict) -> int:
    for key, vector in entries.items():
        _remember(key, vector, persist=False)
    return len(entries)


def _remember(key: str, vector: list[float], persist: bool = True) -> None:
    with _lock:
        _cache[key] = vector
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    if persist and persistent_cache:
        persistent_cache.put(key, vector)


def _lookup(key: str) -> list[float] | None:
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    stored = persistent_cache.get(key) if persistent_cache else None
    if stored:
        _remember(key, stored, persist=False)
    return stored


def _spend_call(owner: str | None) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    with _lock:
        if _usage["day"] != today:
            _usage.update(day=today, calls=0, owners={})
        if _usage["calls"] >= _limit("CONTRA_EMBED_DAILY_LIMIT", 300):
            raise EmbeddingUnavailable("today's search budget is used")
        if owner is not None and _usage["owners"].get(owner, 0) >= _limit("CONTRA_EMBED_ACCOUNT_DAILY_LIMIT", 40):
            raise EmbeddingUnavailable("this account's search budget for today is used")
        _usage["calls"] += 1
        if owner is not None:
            _usage["owners"][owner] = _usage["owners"].get(owner, 0) + 1


def cached_only(texts: list[str]) -> list[list[float]] | None:
    """Vectors for every text if all are cached; otherwise None. Never calls the provider."""
    vectors = [_lookup(key_for(text)) for text in texts]
    return None if any(vector is None for vector in vectors) else vectors


def embed(texts: list[str], owner: str | None = None) -> list[list[float]]:
    """One vector per text. Uncached texts are fetched in a single batched request."""
    if not available():
        raise EmbeddingUnavailable("embeddings are not configured")
    keys = [key_for(text) for text in texts]
    vectors = {key: _lookup(key) for key in set(keys)}
    missing = list(dict.fromkeys(text for text, key in zip(texts, keys) if vectors[key] is None))
    if missing:
        _spend_call(owner)
        body = {"model": MODEL, "input": missing, "dimensions": DIMENSIONS}
        request = Request(API_URL, data=json.dumps(body).encode(), method="POST",
                          headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
                                   "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=8) as response:
                payload = json.load(response)
        except Exception as exc:
            raise EmbeddingUnavailable(f"provider error ({type(exc).__name__})") from exc
        rows = sorted(payload.get("data", []), key=lambda row: row.get("index", 0))
        if len(rows) != len(missing):
            raise EmbeddingUnavailable("provider returned an unexpected number of vectors")
        for text, row in zip(missing, rows):
            vector = row.get("embedding")
            if not isinstance(vector, list) or len(vector) != DIMENSIONS or \
                    any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in vector):
                raise EmbeddingUnavailable("provider returned an invalid vector")
            vector = [round(float(x), 6) for x in vector]
            vectors[key_for(text)] = vector
            _remember(key_for(text), vector)
    return [vectors[key] for key in keys]
