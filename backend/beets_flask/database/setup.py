from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from uuid import uuid4

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from beets_flask.config import get_flask_config
from beets_flask.logger import log

from .models import Base

engine: Engine | None = None
session_factory: scoped_session[Session]


def setup_database(app=None) -> None:
    """Set up the database connection and session factory.

    Initializes the global `engine` and `session_factory` variables
    using the database URI from config.

    Args:
        app: Optional ASGI app instance (unused; kept for backward compat).

    Returns
    -------
        None
    """
    __setup_factory()
    if get_flask_config()["RESET_DB_ON_START"]:
        log.warning("Resetting database due to RESET_DB=True in config")
        _reset_database()

    _create_tables(engine)
    _clear_mb_alias_caches()


def __setup_factory():
    global engine
    global session_factory

    engine = create_engine(get_flask_config()["DATABASE_URI"])
    session_factory = scoped_session(sessionmaker(bind=engine, expire_on_commit=False))


@contextmanager
def db_session_factory(session: Session | None = None):
    """Databases session as context.

    Makes sure sessions are closed at the end.
    If an existing session is provided, it will not be closed at the end.
    This allows to wrap multiple `with db_session()` blocks around each other without closing the outer session.

    Example:
    ```
    with db_session() as session:
        tag.foo = "bar"
        session.merge(tag)
        return tag.to_dict()

    existingSession = session_factory()
    with db_session(session) as s:
        tag.foo = "bar"
        s.merge(tag)
        return tag.to_dict()
    ```
    """
    is_outermost = session is None
    if is_outermost:
        try:
            session = session_factory()
        except NameError:
            __setup_factory()
            session = session_factory()

    try:
        # mypy does not resolve our try/catch for None-Type check. ignore type errors.``
        yield session
        session.commit()  # type: ignore
    except:
        session.rollback()  # type: ignore
        raise
    finally:
        if is_outermost:
            session.close()  # type: ignore


def with_db_session(func):
    """Decorate a function with a db session as a keyword argument to the function.

    Example
    ```
    @with_db_session
    def my_function(session=None):
        tag.foo = "bar"
        session.merge(tag)
        return tag.to_dict()
    ```
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        with db_session_factory() as session:
            kwargs.setdefault("session", session)
            return func(*args, **kwargs)

    return wrapper


def _create_tables(engine) -> None:
    Base.metadata.create_all(bind=engine)
    _run_migrations(engine)


def _run_migrations(engine) -> None:
    """Apply additive schema migrations not covered by create_all."""
    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}

        # Migrate from legacy per-user follow table to global tracked_artist table
        if "user_artist_follow" in tables and "tracked_artist" in tables:
            existing = {
                row[0]
                for row in conn.execute(text("SELECT artist_name FROM tracked_artist"))
            }
            follow_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(user_artist_follow)"))}
            name_col = "display_name" if "display_name" in follow_cols else "artist_name"
            rows = conn.execute(
                text(
                    f"SELECT DISTINCT {name_col}, artist_name, added_at"
                    " FROM user_artist_follow WHERE is_following = 1"
                )
            ).fetchall()
            for display, original, added_at in rows:
                primary = (display or "").strip() or (original or "").strip()
                orig = (original or "").strip() if (original or "").strip() != primary else None
                if primary and primary not in existing:
                    now = datetime.now(timezone.utc)
                    conn.execute(
                        text(
                            "INSERT INTO tracked_artist (id, artist_name, original_name, added_at, created_at, updated_at)"
                            " VALUES (:id, :name, :orig, :at, :now, :now)"
                        ),
                        {"id": str(uuid4()), "name": primary, "orig": orig, "at": added_at or "", "now": now},
                    )
                    existing.add(primary)
            conn.commit()


def _clear_mb_alias_caches() -> None:
    """Clear MusicBrainz alias caches on startup.

    Forces fresh MB alias lookups on next access, ensuring that any fix to
    alias priority selection (e.g. primary locale preference) takes effect
    immediately without waiting for the 24 h Redis TTL to expire.
    """
    try:
        from beets_flask.library_cache import invalidate_artists_list_cache, invalidate_prefix

        invalidate_prefix("mb_alias:")
        invalidate_prefix("mb_artist_name:")
        invalidate_prefix("mb_aliases_all:")
        invalidate_artists_list_cache()
        log.debug("Cleared MB alias caches on startup")
    except Exception as exc:
        log.debug("Could not clear MB alias caches on startup: %s", exc)


def _reset_database():
    # Removes all data from the database but keeps schema
    for t in reversed(Base.metadata.sorted_tables):
        with db_session_factory() as session:
            session.execute(t.delete())
            session.commit()
