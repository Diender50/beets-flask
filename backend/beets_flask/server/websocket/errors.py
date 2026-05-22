from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import NotRequired, ParamSpec, TypedDict, TypeVar

from beets_flask import log


class WebSocketErrorDict(TypedDict):
    error: str
    message: str
    description: NotRequired[str]


Params = ParamSpec("Params")
ReturnType = TypeVar("ReturnType")


def sio_catch_exception(
    func: Callable[Params, Awaitable[ReturnType]],
) -> Callable[Params, Awaitable[ReturnType | WebSocketErrorDict]]:
    @functools.wraps(func)
    async def wrapper(*args, **kwargs) -> ReturnType | WebSocketErrorDict:
        try:
            n_args = func.__code__.co_argcount
            return await func(*args[:n_args], **kwargs)
        except Exception as e:
            log.exception(f"Unhandled websocket error: {e}")
            return WebSocketErrorDict(error=e.__class__.__name__, message=str(e))

    return wrapper


__all__ = ["sio_catch_exception", "WebSocketErrorDict"]
