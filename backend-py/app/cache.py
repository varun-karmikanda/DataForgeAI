"""
Redis cache helpers for DataForge AI.

What lives here
  * LLM answer cache      - same prompt -> same answer, no Groq/Gemini tokens spent
  * Provider cooldowns    - when a provider says "quota used up", remember it (shared across
                            --reload restarts) so we stop sending doomed requests
  * Run locks             - the same prompt is never executed twice at the same moment

Rules
  * Nothing here ever raises. If Redis is down, every function quietly does nothing
    (cache misses, no locks) and the app behaves exactly as it did before caching existed.
  * Every key starts with  df:<CACHE_VERSION>:  - bump CACHE_VERSION in .env to ignore all old entries.

Manual use (from backend-py/, venv active):
    python -m app.cache stats     # how many entries per kind
    python -m app.cache flush     # delete every DataForge cache entry
"""
import hashlib
import json
import os
import time
import uuid

import redis

try:  # lets `python -m app.cache ...` find REDIS_URL in .env; harmless when main.py already did it
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001
    pass

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CACHE_VERSION = os.environ.get("CACHE_VERSION", "v1")
PREFIX = f"df:{CACHE_VERSION}:"

_client: "redis.Redis | None" = None
_down_until = 0.0
_warned = False
_memory_blocks: dict[str, float] = {}  # cooldown fallback when Redis is unreachable
stats = {"hit": 0, "miss": 0}


def _r() -> "redis.Redis | None":
    """Returns a Redis client, or None while Redis is considered down (retries every 30s)."""
    global _client
    if time.time() < _down_until:
        return None
    if _client is None:
        _client = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1, socket_timeout=2)
    return _client


def _mark_down(err: Exception) -> None:
    global _down_until, _client, _warned
    _down_until = time.time() + 30
    _client = None
    if not _warned:
        print(f"[cache] Redis unavailable ({str(err)[:80]}) - running without cache; will retry in 30s")
        _warned = True


def make_key(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{PREFIX}{kind}:{digest}"


def get_json(key: str):
    try:
        client = _r()
        if client is None:
            return None
        raw = client.get(key)
        return json.loads(raw) if raw else None
    except Exception as err:  # noqa: BLE001
        _mark_down(err)
        return None


def set_json(key: str, value, ttl_seconds: int) -> None:
    try:
        client = _r()
        if client is not None:
            client.set(key, json.dumps(value, ensure_ascii=False), ex=max(1, int(ttl_seconds)))
    except Exception as err:  # noqa: BLE001
        _mark_down(err)


# --------------------------------------------------------------------------- cooldowns
def block(provider: str, seconds: float) -> None:
    """Remember that `provider` must not be called for the next `seconds`."""
    seconds = max(5, min(int(seconds), 3600))
    _memory_blocks[provider] = time.time() + seconds
    try:
        client = _r()
        if client is not None:
            client.set(f"{PREFIX}block:{provider}", "1", ex=seconds)
    except Exception as err:  # noqa: BLE001
        _mark_down(err)
    print(f"[cache] {provider} blocked for ~{seconds}s (quota / rate limit)")


def blocked_seconds(provider: str) -> int:
    """Seconds left on the cooldown for `provider` (0 = free to use)."""
    left = max(0, int(_memory_blocks.get(provider, 0) - time.time()))
    try:
        client = _r()
        if client is not None:
            ttl = client.ttl(f"{PREFIX}block:{provider}")
            if ttl and ttl > 0:
                left = max(left, int(ttl))
    except Exception as err:  # noqa: BLE001
        _mark_down(err)
    return left


# --------------------------------------------------------------------------- run locks
def acquire_lock(name: str, ttl_seconds: int = 600) -> "str | None":
    """Returns a token if we own the lock, None if someone else holds it.
    If Redis is down there is nothing to coordinate with, so we report success."""
    token = uuid.uuid4().hex
    try:
        client = _r()
        if client is None:
            return "nolock"
        return token if client.set(f"{PREFIX}lock:{name}", token, nx=True, ex=ttl_seconds) else None
    except Exception as err:  # noqa: BLE001
        _mark_down(err)
        return "nolock"


def lock_held(name: str) -> bool:
    try:
        client = _r()
        return bool(client.exists(f"{PREFIX}lock:{name}")) if client is not None else False
    except Exception as err:  # noqa: BLE001
        _mark_down(err)
        return False


def release_lock(name: str, token: "str | None") -> None:
    if not token or token == "nolock":
        return
    try:
        client = _r()
        if client is not None and client.get(f"{PREFIX}lock:{name}") == token:
            client.delete(f"{PREFIX}lock:{name}")
    except Exception as err:  # noqa: BLE001
        _mark_down(err)


# --------------------------------------------------------------------------- maintenance
def flush() -> int:
    """Deletes every DataForge cache entry for the current CACHE_VERSION. Returns how many."""
    client = _r()
    if client is None:
        return 0
    keys = list(client.scan_iter(match=f"{PREFIX}*", count=500))
    return client.delete(*keys) if keys else 0


def summary() -> dict:
    client = _r()
    out: dict = {}
    if client is None:
        return out
    for key in client.scan_iter(match=f"{PREFIX}*", count=500):
        kind = key[len(PREFIX):].split(":", 1)[0]
        out[kind] = out.get(kind, 0) + 1
    return out


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "flush":
        print(f"deleted {flush()} cache entries")
    else:
        print(summary() or "cache is empty (or Redis is not reachable)")