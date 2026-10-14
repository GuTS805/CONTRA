"""Accounts, password hashing, sessions and simple in-memory rate limits."""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from threading import Lock
from time import monotonic

from . import store

SESSION_COOKIE = "contra_session"
SESSION_DAYS = 7
USERNAME = re.compile(r"^[a-z0-9_]{3,32}$")
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${key.hex()}"


def check_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        # Burn comparable time so a missing account is not faster to reject.
        hashlib.scrypt(password.encode(), salt=b"0" * 16, **_SCRYPT)
        return False
    _, salt, key = stored.split("$")
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
    return hmac.compare_digest(candidate.hex(), key)


def validate_credentials(username, password) -> tuple[str, str]:
    if not isinstance(username, str) or not isinstance(password, str):
        raise ValueError("username and password are required")
    username = username.strip().lower()
    if not USERNAME.match(username):
        raise ValueError("Username must be 3-32 characters: lowercase letters, digits or underscore")
    if username.startswith("guest_"):
        raise ValueError("Usernames starting with guest_ are reserved")
    if not 8 <= len(password) <= 128:
        raise ValueError("Password must be 8-128 characters")
    return username, password


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_user_id() -> str:
    return "u_" + secrets.token_hex(8)


def signup(db, username, password) -> dict:
    username, password = validate_credentials(username, password)
    return store.insert_user(db, new_user_id(), username, hash_password(password))


def guest(db) -> dict:
    return store.insert_user(db, new_user_id(), "guest_" + secrets.token_hex(4), None, is_guest=True)


def login(db, username, password) -> dict | None:
    if not isinstance(username, str) or not isinstance(password, str) or len(password) > 128:
        return None
    user = store.user_by_name(db, username.strip().lower())
    if not check_password(password, user["password_hash"] if user else None):
        return None
    return {"id": user["id"], "username": user["username"], "is_guest": bool(user["is_guest"])}


def start_session(db, user_id) -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    store.save_session(db, _token_hash(token), user_id, expires.isoformat())
    return token, SESSION_DAYS * 86400


def user_for_token(db, token) -> dict | None:
    return store.session_user(db, _token_hash(token)) if token else None


def end_session(db, token) -> None:
    if token:
        store.delete_session(db, _token_hash(token))


class RateLimiter:
    """Sliding-window counter per key. Process-local, which suits one server instance."""

    def __init__(self):
        self._events = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = monotonic()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] > window_seconds:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True


limiter = RateLimiter()
