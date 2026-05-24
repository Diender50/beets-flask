"""Auth utilities: password hashing and JWT creation/decoding."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

_ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(user_id: str, secret: str, expiry_hours: int) -> str:
    expire = datetime.now(UTC) + timedelta(hours=expiry_hours)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_token(token: str, secret: str) -> str:
    """Return user_id from a valid token; raise ValueError on failure."""
    try:
        data = jwt.decode(token, secret, algorithms=[_ALGORITHM])
        user_id: str | None = data.get("sub")
        if not user_id:
            raise ValueError("Token missing sub claim")
        return user_id
    except JWTError as exc:
        raise ValueError(str(exc)) from exc
