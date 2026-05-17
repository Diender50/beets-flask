from __future__ import annotations

from beets_flask.logger import log
from beets_flask.redis import redis_conn

ARTISTS_CACHE_PREFIX = "library:artists:"
MISSING_CACHE_PREFIX = "library:artists:missing:"


def get_json_cache(key: str) -> str | None:
    try:
        cached = redis_conn.get(key)
    except Exception as exc:  # pragma: no cover
        log.debug(f"Redis get failed for key '{key}': {exc}")
        return None

    if cached is None:
        return None

    if isinstance(cached, bytes):
        return cached.decode("utf-8")
    return str(cached)


def set_json_cache(key: str, payload: str, ttl_seconds: int) -> None:
    try:
        redis_conn.setex(key, ttl_seconds, payload)
    except Exception as exc:  # pragma: no cover
        log.debug(f"Redis set failed for key '{key}': {exc}")


def invalidate_prefix(prefix: str) -> int:
    removed = 0
    try:
        for key in redis_conn.scan_iter(f"{prefix}*"):
            redis_conn.delete(key)
            removed += 1
    except Exception as exc:  # pragma: no cover
        log.debug(f"Redis invalidation failed for prefix '{prefix}': {exc}")
    return removed


def invalidate_artists_cache() -> int:
    removed_artists = invalidate_prefix(ARTISTS_CACHE_PREFIX)
    removed_missing = invalidate_prefix(MISSING_CACHE_PREFIX)
    return removed_artists + removed_missing
