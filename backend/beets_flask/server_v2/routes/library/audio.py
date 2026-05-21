import os

from beets import util as beets_util
from fastapi import APIRouter
from fastapi.responses import StreamingResponse, Response

from beets_flask.logger import log
from beets_flask.server.exceptions import IntegrityException, NotFoundException
# All pure-Python audio helpers (FFmpegStreamer, transcode_to_webm, etc.) reused as-is.
from beets_flask.server.routes.library.audio import (
    audio_peaks_cached,
    cached_async_iterator,
    transcodeCache,
    transcode_to_webm,
)
from beets_flask.server_v2.dependencies import BeetsLib

router = APIRouter(tags=["library"])


@router.get("/item/{item_id}/audio")
async def item_audio(item_id: int, lib: BeetsLib) -> StreamingResponse:
    item = lib.get_item(item_id)
    if not item:
        raise NotFoundException(f"Item with beets_id:'{item_id}' not found in beets db.")

    item_path = beets_util.syspath(item.path)
    if not os.path.exists(item_path):
        raise IntegrityException(
            f"Item file '{item_path}' does not exist for item beets_id:'{item_id}'."
        )

    it = await transcode_to_webm(item_path)
    return StreamingResponse(
        cached_async_iterator(item_path, it, transcodeCache),
        media_type="audio/webm",
    )


@router.get("/item/{item_id}/audio/peaks")
async def item_audio_peaks(item_id: int, lib: BeetsLib) -> Response:
    item = lib.get_item(item_id)
    if not item:
        raise NotFoundException(f"Item with beets_id:'{item_id}' not found in beets db.")

    item_path = beets_util.syspath(item.path)
    if not os.path.exists(item_path):
        raise IntegrityException(
            f"Item file '{item_path}' does not exist for item beets_id:'{item_id}'."
        )

    peaks = await audio_peaks_cached(item_path)
    return Response(content=peaks.tobytes(), media_type="application/octet-stream")
