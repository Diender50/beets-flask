from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from beets.library import Library

from beets_flask.database.models.users import UserInDb

_bearer = HTTPBearer(auto_error=False)


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
        close = getattr(lib, "close", None)
        if callable(close):
            close()


def _get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> UserInDb:
    from beets_flask.config.flask_config import get_flask_config
    from beets_flask.server.auth_utils import decode_token
    from beets_flask.server.exceptions import UnauthorizedException

    if credentials is None:
        raise UnauthorizedException("Missing authentication token")

    try:
        user_id = decode_token(
            credentials.credentials,
            get_flask_config().SECRET_KEY,
        )
    except ValueError as exc:
        raise UnauthorizedException(str(exc)) from exc

    user = db.get(UserInDb, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedException("User not found or inactive")
    return user


def _require_permission(permission: str):
    """Return a FastAPI dependency that enforces a single permission flag."""

    def _dep(user: UserInDb = Depends(_get_current_user)) -> UserInDb:
        from beets_flask.server.exceptions import ForbiddenException

        if user.is_admin:
            return user
        if not getattr(user, permission, False):
            raise ForbiddenException(f"Permission required: {permission}")
        return user

    return _dep


def _require_admin(user: UserInDb = Depends(_get_current_user)) -> UserInDb:
    from beets_flask.server.exceptions import ForbiddenException

    if not user.is_admin:
        raise ForbiddenException("Admin access required")
    return user


# Convenience type aliases for route signatures:
#   async def my_route(db: DbSession, lib: BeetsLib): ...
DbSession = Annotated[Session, Depends(get_db)]
BeetsLib = Annotated["Library", Depends(get_beets_lib)]
CurrentUser = Annotated[UserInDb, Depends(_get_current_user)]
RequireAdmin = Annotated[UserInDb, Depends(_require_admin)]


def require_permission(permission: str) -> Annotated[UserInDb, Depends]:
    """Factory for permission-gated dependencies.

    Usage::

        async def route(user: Annotated[UserInDb, require_permission("can_retag")]): ...
    """
    return Annotated[UserInDb, Depends(_require_permission(permission))]
