from contextlib import contextmanager
from functools import wraps

from sqlalchemy import Engine, create_engine
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


def _reset_database():
    # Removes all data from the database but keeps schema
    for t in reversed(Base.metadata.sorted_tables):
        with db_session_factory() as session:
            session.execute(t.delete())
            session.commit()
