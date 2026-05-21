import os
from io import BytesIO

from beets import util as beets_util
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import RedirectResponse
from mediafile import Image, MediaFile
from PIL import Image as PILImage
from typing import cast

from beets_flask.logger import log
from beets_flask.server.exceptions import (
    IntegrityException,
    InvalidUsageException,
    NotFoundException,
)
from beets_flask.server_v2.dependencies import BeetsLib

router = APIRouter(tags=["library"])

SIZE_PRESETS = {
    "small": (256, 256),
    "medium": (512, 512),
    "large": (1024, 1024),
    "original": None,
}


def parse_size(size_key: str) -> tuple[int, int] | None:
    if size_key not in SIZE_PRESETS:
        raise InvalidUsageException(
            f"Invalid size key '{size_key}'. Supported: {', '.join(SIZE_PRESETS)}"
        )
    return SIZE_PRESETS[size_key]


def get_image_data_from_file(filepath: str, index: int = 0) -> BytesIO:
    if not os.path.exists(filepath):
        raise IntegrityException(f"File '{filepath}' does not exist.")
    mediafile = MediaFile(filepath)
    images = mediafile.images
    if not images or len(images) <= index:
        raise NotFoundException(f"File has no cover art at index {index}: '{filepath}'.")
    im: Image = cast(Image, images[index])
    return BytesIO(im.data)


def get_image_count_from_file(filepath: str) -> int:
    return len(MediaFile(filepath).images or [])


def _send_image(img_data: BytesIO, size: tuple[int, int] | None) -> Response:
    if size:
        img_data = _resize(img_data, size)
    return Response(
        content=img_data.read(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _resize(img_data: BytesIO, size: tuple[int, int]) -> BytesIO:
    image = PILImage.open(img_data)
    image.thumbnail(size)
    out = BytesIO()
    image.convert("RGB").save(out, format="png")
    out.seek(0)
    return out


# -------------------------------- Item routes ------------------------------- #


@router.get("/item/{item_id}/nArtworks")
async def item_art_idx(item_id: int, lib: BeetsLib) -> dict:
    item = lib.get_item(item_id)
    if not item:
        raise NotFoundException(f"Item with beets_id:'{item_id}' not found in beets db.")
    return {"count": get_image_count_from_file(beets_util.syspath(item.path))}


@router.get("/item/{item_id}/art")
async def item_art(item_id: int, lib: BeetsLib, index: int = 0, size: str = "small") -> Response:
    size_tuple = parse_size(size)
    item = lib.get_item(item_id)
    if not item:
        raise NotFoundException(f"Item with beets_id:'{item_id}' not found in beets db.")
    img_data = get_image_data_from_file(beets_util.syspath(item.path), index)
    return _send_image(img_data, size_tuple)


# ------------------------------- Album routes ------------------------------- #


@router.get("/album/{album_id}/art")
async def album_art(album_id: int, lib: BeetsLib, index: int = 0, size: str = "small") -> Response:
    size_tuple = parse_size(size)
    album = lib.get_album(album_id)
    if not album:
        raise NotFoundException(f"Album with beets_id:'{album_id}' not found in beets db.")

    if album.artpath and index == 0:
        art_path = beets_util.syspath(album.artpath)
        if not os.path.exists(art_path):
            raise IntegrityException(
                f"Album art file '{art_path}' does not exist for album beets_id:'{album_id}'."
            )
        return _send_image(BytesIO(open(art_path, "rb").read()), size_tuple)

    items = list(album.items())
    if not items:
        raise IntegrityException(f"Album has no items: '{album_id}'.")

    return RedirectResponse(
        url=f"/api_v1/library/item/{items[0].id}/art?index={index}&size={size}",
        status_code=302,
    )


# -------------------------------- File routes ------------------------------- #


@router.get("/files/{filepath}/nArtworks")
async def file_art_idx(filepath: str) -> dict:
    filepath = bytes.fromhex(filepath).decode("utf-8")
    return {"count": get_image_count_from_file(filepath)}


@router.get("/file/{filepath}/art")
async def file_art(filepath: str, index: int = 0, size: str = "small") -> Response:
    filepath = bytes.fromhex(filepath).decode("utf-8")
    size_tuple = parse_size(size)
    img_data = get_image_data_from_file(filepath, index)
    return _send_image(img_data, size_tuple)
