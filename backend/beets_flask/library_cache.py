from __future__ import annotations

import re

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


# ──────────────────────── DB-backed missing-albums cache ─────────────────────


def get_db_missing_cache(artist_name: str) -> str | None:
    """Read missing-albums JSON from the persistent SQLite cache."""
    try:
        from beets_flask.database.models.states import MissingAlbumCacheInDb
        from beets_flask.database.setup import session_factory

        session = session_factory()
        try:
            entry = session.query(MissingAlbumCacheInDb).filter_by(artist_name=artist_name).first()
            return entry.albums_json if entry is not None else None
        finally:
            session.close()
    except Exception as exc:
        log.debug(f"DB missing cache get failed for '{artist_name}': {exc}")
        return None


def set_db_missing_cache(artist_name: str, payload: str) -> None:
    """Upsert missing-albums JSON into the persistent SQLite cache."""
    try:
        from beets_flask.database.models.states import MissingAlbumCacheInDb
        from beets_flask.database.setup import session_factory

        session = session_factory()
        try:
            entry = session.query(MissingAlbumCacheInDb).filter_by(artist_name=artist_name).first()
            if entry is None:
                entry = MissingAlbumCacheInDb(artist_name=artist_name, albums_json=payload)
                session.add(entry)
            else:
                entry.albums_json = payload
            session.commit()
        finally:
            session.close()
    except Exception as exc:
        log.debug(f"DB missing cache set failed for '{artist_name}': {exc}")


def invalidate_db_missing_cache(artist_name: str) -> bool:
    """Delete the persistent DB cache entry for one artist. Returns True if deleted."""
    try:
        from beets_flask.database.models.states import MissingAlbumCacheInDb
        from beets_flask.database.setup import session_factory

        session = session_factory()
        try:
            deleted = (
                session.query(MissingAlbumCacheInDb)
                .filter_by(artist_name=artist_name)
                .delete()
            )
            session.commit()
            return bool(deleted)
        finally:
            session.close()
    except Exception as exc:
        log.debug(f"DB missing cache invalidate failed for '{artist_name}': {exc}")
        return False


def invalidate_missing_cache_for_string(albumartist: str) -> None:
    """Invalidate Redis + DB missing-albums cache for all artists encoded in *albumartist*.

    Handles multi-artist strings by splitting on the configured separators so that
    importing "Artist A feat. Artist B" correctly invalidates both artists' caches.
    """
    try:
        from beets_flask.config import get_config

        separators: list[str] = get_config()["gui"]["library"]["artist_separators"].as_str_seq()
    except Exception:
        separators = []

    if separators:
        pattern = "|".join(map(re.escape, separators))
        names = [n.strip() for n in re.split(pattern, albumartist) if n.strip()]
    else:
        names = [albumartist.strip()] if albumartist.strip() else []

    for name in names:
        cache_key = f"{MISSING_CACHE_PREFIX}{name}"
        try:
            redis_conn.delete(cache_key)
        except Exception as exc:
            log.debug(f"Redis delete failed for '{cache_key}': {exc}")
        invalidate_db_missing_cache(name)
        log.debug(f"Invalidated missing albums cache for artist '{name}'")

