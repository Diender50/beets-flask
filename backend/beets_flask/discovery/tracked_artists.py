"""Global tracked-artist list (shared across all users)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from beets_flask.database.models.users import TrackedArtistInDb
from beets_flask.database.setup import db_session_factory


def _get_row(session, name: str) -> TrackedArtistInDb | None:
    return session.execute(
        select(TrackedArtistInDb).where(TrackedArtistInDb.artist_name == name)
    ).scalars().first()


def add_tracked_artist(name: str, original_name: str | None = None) -> dict:
    """Add artist to the global tracked list (no-op if already present)."""
    now = datetime.now(UTC).isoformat()
    with db_session_factory() as session:
        row = _get_row(session, name)
        if row is None:
            session.add(TrackedArtistInDb(artist_name=name, original_name=original_name, added_at=now))
        else:
            if original_name is not None:
                row.original_name = original_name
        session.commit()
    return {"name": name, "added_at": now, "original_name": original_name}


def remove_tracked_artist(name: str) -> bool:
    """Hard-delete artist from tracked list. Returns True if row existed."""
    with db_session_factory() as session:
        row = _get_row(session, name)
        if row:
            session.delete(row)
            session.commit()
            return True
    return False


def get_tracked_artists() -> list[dict]:
    """Return all globally tracked artists, sorted alphabetically."""
    with db_session_factory() as session:
        rows = session.execute(
            select(TrackedArtistInDb).order_by(TrackedArtistInDb.artist_name)
        ).scalars().all()
        return [
            {"name": r.artist_name, "added_at": r.added_at, "original_name": r.original_name}
            for r in rows
        ]


def is_tracked(name: str) -> bool:
    with db_session_factory() as session:
        return _get_row(session, name) is not None


def get_tracked_artist(name: str) -> dict | None:
    with db_session_factory() as session:
        row = _get_row(session, name)
        if row is None:
            return None
        return {"name": row.artist_name, "added_at": row.added_at, "original_name": row.original_name}
