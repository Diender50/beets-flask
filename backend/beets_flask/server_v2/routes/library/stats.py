from pathlib import Path
from typing_extensions import TypedDict

from fastapi import APIRouter

from beets_flask.config import get_config
from beets_flask.disk import dir_size
from beets_flask.server_v2.dependencies import BeetsLib

router = APIRouter(tags=["library"])


class LibraryStats(TypedDict):
    libraryPath: str
    items: int
    albums: int
    artists: int
    genres: int
    labels: int
    size: int
    lastItemAdded: int | None
    lastItemModified: int | None
    runtime: float


@router.get("/stats")
async def stats(lib: BeetsLib) -> LibraryStats:
    config = get_config()

    with lib.transaction() as tx:
        album_stats = tx.query(
            "SELECT COUNT(*), COUNT(DISTINCT genre), COUNT(DISTINCT label), COUNT(DISTINCT albumartist) FROM albums"
        )
        items_stats = tx.query(
            "SELECT COUNT(*), MAX(added), MAX(mtime), SUM(length) FROM items"
        )

    lib_path = str(config["directory"].get(str))

    return {
        "libraryPath": str(config["directory"].as_str()),
        "items": items_stats[0][0],
        "albums": album_stats[0][0],
        "artists": album_stats[0][3],
        "genres": album_stats[0][1],
        "labels": album_stats[0][2],
        "size": dir_size(Path(lib_path)),
        "lastItemAdded": (
            round(items_stats[0][1] * 1000) if items_stats[0][1] is not None else None
        ),
        "lastItemModified": (
            round(items_stats[0][2] * 1000) if items_stats[0][2] is not None else None
        ),
        "runtime": items_stats[0][3] or 0,
    }
