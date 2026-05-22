import os
from pathlib import Path

from beets import util as beets_util
from fastapi import APIRouter
from tinytag import TinyTag

from beets_flask.server.exceptions import IntegrityException, NotFoundException
from beets_flask.server.dependencies import BeetsLib

router = APIRouter(tags=["library"])


@router.get("/item/{item_id}/metadata")
async def item_metadata(item_id: int, lib: BeetsLib) -> dict:
    item = lib.get_item(item_id)
    if not item:
        raise NotFoundException(f"Item with beets_id:'{item_id}' not found in beets db.")

    item_path = beets_util.syspath(item.path)
    if not os.path.exists(item_path):
        raise IntegrityException(
            f"Item file '{item_path}' does not exist for item beets_id:'{item_id}'."
        )
    return _get_metadata(item_path)


@router.get("/file/{filepath}/metadata")
async def file_metadata(filepath: str) -> dict:
    """filepath is hex-encoded to handle special characters in URLs."""
    filepath = bytes.fromhex(filepath).decode("utf-8")
    if not os.path.exists(filepath):
        raise NotFoundException(f"File '{filepath}' does not exist.")
    return _get_metadata(filepath)


def _get_metadata(file: str | Path) -> dict:
    tags = TinyTag.get(file).as_dict()
    tags["filename"] = os.path.basename(file)
    return tags
