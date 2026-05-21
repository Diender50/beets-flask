"""Library resource CRUD — migrated from server/routes/library/resources.py.

The original uses a @resource/@resource_query decorator that dispatches on request.method.
FastAPI version: split into explicit GET / DELETE / PATCH endpoints.
PaginatedQuery.total() receives lib explicitly (removes g.lib dependency).
"""

from __future__ import annotations

from typing import Any

from beets.dbcore.query import Sort
from beets.library import Album, Item, Library, parse_query_string
from fastapi import APIRouter

from beets_flask.config import get_config
from beets_flask.logger import log
from beets_flask.server.exceptions import NotFoundException
from beets_flask.server.routes.exception import InvalidUsageException
from beets_flask.server.utility import pop_query_param
# Pure-Python helpers (no Quart) reused directly.
from beets_flask.server.routes.library.resources import (
    Cursor,
    PaginatedQuery,
    _rep,
    delete_entities,
    update_entities,
)
from beets_flask.server_v2.dependencies import BeetsLib

router = APIRouter(tags=["library"])


# ──────────────────────────────────────────────────────────────
# Albums
# ──────────────────────────────────────────────────────────────

@router.get("/album/{id}")
async def get_album(id: int, lib: BeetsLib, expand: bool = False, minimal: bool = False) -> dict:
    item = lib.get_album(id)
    if not item:
        raise NotFoundException(f"Album with beets_id:'{id}' not found in beets db.")
    return _rep(item, expand=expand, minimal=minimal)


@router.delete("/album/{id}")
async def delete_album(id: int, lib: BeetsLib, delete: bool = False) -> dict:
    item = lib.get_album(id)
    if not item:
        raise NotFoundException(f"Album with beets_id:'{id}' not found in beets db.")
    delete_entities([item], delete)
    return {"deleted": True}


@router.patch("/album/{id}")
async def patch_album(id: int, lib: BeetsLib, body: dict[str, Any]) -> dict:
    item = lib.get_album(id)
    if not item:
        raise NotFoundException(f"Album with beets_id:'{id}' not found in beets db.")
    item = update_entities([item], body)[0]
    return _rep(item)


@router.get("/album/bf_id/{bf_id}")
async def album_by_bf_id(bf_id: str, lib: BeetsLib) -> dict:
    albums = lib.albums(f"gui_import_id:{bf_id}")
    if len(albums) == 0:
        raise NotFoundException(f"Album with gui_import_id:'{bf_id}' not found in beets db.")
    if len(albums) > 1:
        log.warning(f"Multiple albums with gui_import_id:'{bf_id}'. Returning first.")
    return _rep(albums[0])


@router.get("/albums")
@router.get("/albums/{query:path}")
async def all_albums(
    lib: BeetsLib,
    query: str = "",
    cursor: str | None = None,
    order_by: str = "added",
    order_dir: str = "DESC",
    n_items: int = 50,
) -> dict:
    if cursor is not None:
        cur = Cursor.from_string(cursor)
    else:
        cur = Cursor(order_by_column=order_by, order_by_direction=order_dir, last_order_by_value=None, last_id=None)

    sub_query = parse_query_string(query, Album)
    paginated = PaginatedQuery(cursor=cur, sub_query=sub_query, n_items=n_items)
    albums = list(lib.albums(paginated, paginated))

    next_url: str | None = None
    total = _total_with_lib(paginated, lib, "albums")
    if len(albums) == n_items and albums:
        last = albums[-1]
        cur.last_order_by_value = str(getattr(last, cur.order_by_column, None))
        cur.last_id = str(last.id)
        next_url = f"/api_v1/library/albums/{query}?cursor={cur.to_string()}&n_items={n_items}"

    return {
        "albums": [_rep(a, expand=False, minimal=True) for a in albums],
        "next": next_url,
        "total": total,
    }


@router.get("/artist/{artist_name:path}/albums")
async def albums_by_artist(artist_name: str, lib: BeetsLib, expand: bool = False, minimal: bool = False) -> list:
    with lib.transaction() as tx:
        rows = tx.query("SELECT id FROM albums WHERE instr(albumartist, ?) > 0", (artist_name,))
    return [_rep(lib.get_album(row[0]), expand=expand, minimal=minimal) for row in rows]


# ──────────────────────────────────────────────────────────────
# Items
# ──────────────────────────────────────────────────────────────

@router.get("/item/{id}")
async def get_item(id: int, lib: BeetsLib, expand: bool = False, minimal: bool = False) -> dict:
    item = lib.get_item(id)
    if not item:
        raise NotFoundException(f"Item with beets_id:'{id}' not found in beets db.")
    return _rep(item, minimal=minimal)


@router.delete("/item/{id}")
async def delete_item(id: int, lib: BeetsLib, delete: bool = False) -> dict:
    item = lib.get_item(id)
    if not item:
        raise NotFoundException(f"Item with beets_id:'{id}' not found in beets db.")
    delete_entities([item], delete)
    return {"deleted": True}


@router.patch("/item/{id}")
async def patch_item(id: int, lib: BeetsLib, body: dict[str, Any]) -> dict:
    item = lib.get_item(id)
    if not item:
        raise NotFoundException(f"Item with beets_id:'{id}' not found in beets db.")
    item = update_entities([item], body)[0]
    return _rep(item)


@router.get("/items")
@router.get("/items/{query:path}")
async def all_items(
    lib: BeetsLib,
    query: str = "",
    cursor: str | None = None,
    order_by: str = "added",
    order_dir: str = "DESC",
    n_items: int = 50,
) -> dict:
    if cursor is not None:
        cur = Cursor.from_string(cursor)
    else:
        cur = Cursor(order_by_column=order_by, order_by_direction=order_dir, last_order_by_value=None, last_id=None)

    sub_query = parse_query_string(query, Item)
    paginated = PaginatedQuery(cursor=cur, sub_query=sub_query, n_items=n_items, table="items")
    items = list(lib.items(paginated, paginated))

    next_url: str | None = None
    total = _total_with_lib(paginated, lib, "items")
    if len(items) == n_items and items:
        last = items[-1]
        cur.last_order_by_value = str(getattr(last, cur.order_by_column, None))
        cur.last_id = str(last.id)
        next_url = f"/api_v1/library/items/{query}?cursor={cur.to_string()}&n_items={n_items}"

    return {
        "items": [_rep(i, expand=False, minimal=True) for i in items],
        "next": next_url,
        "total": total,
    }


@router.get("/artist/{artist_name:path}/items")
async def items_by_artist(artist_name: str, lib: BeetsLib, expand: bool = False, minimal: bool = False) -> list:
    with lib.transaction() as tx:
        rows = tx.query("SELECT id FROM items WHERE instr(artist, ?) > 0", (artist_name,))
    return [_rep(lib.get_item(row[0]), expand=expand, minimal=minimal) for row in rows]


# ──────────────────────────────────────────────────────────────
# Helper — PaginatedQuery.total() without g.lib
# ──────────────────────────────────────────────────────────────

def _total_with_lib(paginated: PaginatedQuery, lib: Library, table: str) -> int:
    if paginated._sub_query:
        cs, vs = paginated._sub_query[0].clause()
    else:
        cs, vs = "1=1", ()

    with lib.transaction() as tx:
        return tx.query(f"SELECT COUNT(*) FROM {table} WHERE {cs}", vs)[0][0]
