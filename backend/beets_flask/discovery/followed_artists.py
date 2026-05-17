"""SQLite-backed storage for followed artists (artists not yet in the beets library)."""

from datetime import datetime, timezone

from beets_flask.database.models.states import FollowedArtistInDb
from beets_flask.database.setup import db_session_factory


def _get_by_name(session, name: str) -> FollowedArtistInDb | None:
    return session.query(FollowedArtistInDb).filter_by(name=name).first()


def follow_artist(name: str) -> dict:
    """Add an artist to the followed set. Returns the stored metadata."""
    now = datetime.now(timezone.utc).isoformat()
    with db_session_factory() as session:
        existing = _get_by_name(session, name)
        if existing:
            return {"name": existing.name, "added_at": existing.added_at}
        record = FollowedArtistInDb(name=name, added_at=now)
        session.add(record)
        session.commit()
    return {"name": name, "added_at": now}


def unfollow_artist(name: str) -> bool:
    """Remove an artist from the followed set. Returns True if it was present."""
    with db_session_factory() as session:
        record = _get_by_name(session, name)
        if record:
            session.delete(record)
            session.commit()
            return True
    return False


def get_followed_artists() -> list[dict]:
    """Return all followed artists sorted alphabetically."""
    with db_session_factory() as session:
        records = session.query(FollowedArtistInDb).order_by(FollowedArtistInDb.name).all()
        return [{"name": r.name, "added_at": r.added_at} for r in records]


def is_followed(name: str) -> bool:
    with db_session_factory() as session:
        return _get_by_name(session, name) is not None
