"""Telegram authentication, independent of the ML runtime."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def validate_init_data(raw: str, token: str, allowed: set[int], now=None) -> dict:
    now = int(time.time() if now is None else now)
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("Duplicate fields")
    received = fields.pop("hash", "")
    # The bot-token HMAC includes all fields other than hash (including signature).
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not token or not hmac.compare_digest(expected, received):
        raise ValueError("Invalid Telegram signature")
    age = now - int(fields.get("auth_date", "0"))
    if age < -30 or age > 3600:
        raise ValueError("Telegram login expired")
    user = json.loads(fields.get("user", "{}"))
    if not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] not in allowed:
        raise PermissionError("Access denied")
    return user


def make_session(user_id: int, token: str, now=None) -> str:
    payload = f"{user_id}.{int(time.time() if now is None else now) + 86400}"
    signature = hmac.new(token.encode(), ("voicebox-session:" + payload).encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def read_session(value: str, token: str, allowed: set[int], now=None) -> int:
    uid, expiry, signature = value.split(".")
    payload = f"{uid}.{expiry}"
    expected = hmac.new(token.encode(), ("voicebox-session:" + payload).encode(), hashlib.sha256).hexdigest()
    user_id = int(uid)
    if not token or not hmac.compare_digest(signature, expected) or int(expiry) <= int(time.time() if now is None else now):
        raise ValueError("Session expired")
    if user_id not in allowed:
        raise PermissionError("Access denied")
    return user_id
