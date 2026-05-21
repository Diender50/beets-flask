from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from beets.library import Library


def get_db() -> Generator[Session, None, None]:
    from beets_flask.database.setup import session_factory

    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_beets_lib() -> Generator[Library, None, None]:
    from beets.ui import _open_library
    from beets_flask.config import get_config

    lib = _open_library(get_config())
    try:
        yield lib
    finally:
        lib.close()


# Convenience type aliases for route signatures:
#   async def my_route(db: DbSession, lib: BeetsLib): ...
DbSession = Annotated[Session, Depends(get_db)]
BeetsLib = Annotated["Library", Depends(get_beets_lib)]
