import asyncio
import os
import time
from asyncio.subprocess import PIPE, Process
from collections.abc import AsyncIterator, Hashable
from typing import Any, TypeVar

import aiofiles
import numpy as np
from beets import util as beets_util
from cachetools import Cache, TTLCache
from cachetools.keys import hashkey
from fastapi import APIRouter
from fastapi.responses import Response, StreamingResponse

from beets_flask.logger import log
from beets_flask.server.dependencies import BeetsLib
from beets_flask.server.exceptions import IntegrityException, NotFoundException

router = APIRouter(tags=["library"])

# ─── Audio transcoding helpers ───────────────────────────────────────────────

transcodeCache: Cache[Hashable, Any] = TTLCache(maxsize=128, ttl=60 * 60)
peaksCache: Cache[Hashable, Any] = TTLCache(maxsize=128, ttl=60 * 60)


class FFmpegError(RuntimeError):
    def __init__(self, returncode: int, stderr: str):
        super().__init__(f"FFmpeg failed with code {returncode}: {stderr.strip()}")
        self.returncode = returncode
        self.stderr = stderr


FATAL_PATTERNS = ["Error", "Invalid data", "partial file", "Could not"]


class FFmpegStreamer:
    process: Process | None
    _stderr_lines: list[str] = []
    chunk_size: int = 4096

    def __init__(self):
        self.process = None

    async def start(self, *ffmpeg_args):
        self._stderr_lines = []
        self.process = await asyncio.create_subprocess_exec(
            "ffmpeg", *ffmpeg_args, stdin=PIPE, stdout=PIPE, stderr=PIPE,
        )
        asyncio.create_task(self._drain_stderr())

    async def stream_file(self, file_path: str | None) -> AsyncIterator[bytes]:
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("FFmpeg process not started. Call start() first.")

        writer = None
        if file_path is not None and os.path.exists(file_path):
            writer = asyncio.create_task(self._write_input(self._file_chunker(file_path)))

        start = time.process_time_ns()
        try:
            while not self.process.stdout.at_eof():
                chunk = await self.process.stdout.read(self.chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            if writer is not None:
                await writer
            return_code = await self.process.wait()
            if return_code != 0 or self._stderr_lines:
                raise FFmpegError(return_code, "".join(self._stderr_lines))
            log.debug(f"Transcoded {file_path} in {(time.process_time_ns() - start) / 1_000_000_000:.2f}s")

    async def stream(self) -> AsyncIterator[bytes]:
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("FFmpeg process not started. Call start() first.")

        start = time.process_time_ns()
        try:
            while not self.process.stdout.at_eof():
                chunk = await self.process.stdout.read(self.chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            return_code = await self.process.wait()
            if return_code != 0 or self._stderr_lines:
                raise FFmpegError(return_code, "".join(self._stderr_lines))
            log.info(f"Streamed in {(time.process_time_ns() - start) / 1_000_000_000:.2f} s")

    async def _drain_stderr(self):
        assert self.process and self.process.stderr
        while True:
            line = await self.process.stderr.readline()
            if not line:
                break
            decoded = line.decode().strip()
            self._stderr_lines.append(decoded)
            log.error(f"FFmpeg stderr: {decoded}")

    async def _write_input(self, input_stream: AsyncIterator[bytes]):
        assert self.process is not None and self.process.stdin is not None
        async for data in input_stream:
            self.process.stdin.write(data)
            await self.process.stdin.drain()
        self.process.stdin.close()

    async def _file_chunker(self, path: str, size: int = 64 * 1024) -> AsyncIterator[bytes]:
        semaphore = asyncio.Semaphore(size * 100)
        try:
            async with aiofiles.open(path, "rb") as file:
                while True:
                    await semaphore.acquire()
                    chunk = await file.read(size)
                    if chunk == b"":
                        break
                    yield chunk
                    semaphore.release()
                log.warning(f"Finished reading file {path}")
        except asyncio.CancelledError:
            log.info(f"File reading cancelled for {path}")
            raise
        except Exception as e:
            log.error(f"Error reading file {path}: {e}")
            raise


T = TypeVar("T")


async def cached_async_iterator(
    key: Hashable, iterator: AsyncIterator[T], cache: Cache[Hashable, list[T]]
) -> AsyncIterator[T]:
    try:
        cached = []
        if key in cache:
            log.debug(f"Using cached data for {key}")
            cached = cache[key]
        else:
            log.debug(f"Caching data for {key}")
            async for item in iterator:
                cached.append(item)
                yield item
            cache[key] = cached
            return
        for item in cached:
            yield item
    except Exception:
        cache.pop(key, None)
        raise


STREAMABLE_FORMATS = {"wav", "flac", "ogg", "pcm"}
CONTAINER_FORMATS = {"m4a", "mp4", "mov", "alac", "aac", "mp3"}


async def transcode_to_webm(file_path: str) -> AsyncIterator[bytes]:
    ffmpeg_streamer = FFmpegStreamer()
    ext = file_path.split(".")[-1].lower()

    # fmt: off
    if ext in STREAMABLE_FORMATS:
        await ffmpeg_streamer.start(*[
            "-hide_banner", "-loglevel", "error",
            "-fflags", "nobuffer", "-flush_packets", "0", "-probesize", "32",
            "-f", ext, "-i", "-",
            "-vn", "-sn", "-dn", "-preset", "ultrafast",
            "-map_metadata", "-1", "-map", "0:a",
            "-codec:a", "libopus", "-b:a", "128k", "-f", "webm", "-",
        ])
        # fmt: on
        return ffmpeg_streamer.stream_file(file_path)
    else:
        await ffmpeg_streamer.start(*[
            "-hide_banner", "-loglevel", "error", "-nostdin",
            "-fflags", "nobuffer", "-flush_packets", "0", "-probesize", "32",
            "-i", str(file_path),
            "-vn", "-sn", "-dn", "-preset", "ultrafast",
            "-map_metadata", "-1", "-map", "0:a",
            "-codec:a", "libopus", "-b:a", "128k", "-f", "webm", "-",
        ])
        # fmt: on
        if ffmpeg_streamer.process and ffmpeg_streamer.process.stdin:
            ffmpeg_streamer.process.stdin.close()
        return ffmpeg_streamer.stream()


peaksCache = TTLCache(maxsize=128, ttl=60 * 60)


async def audio_peaks_cached(item_path: str) -> np.ndarray:
    cache_key = hashkey(item_path)
    if cache_key in peaksCache:
        log.debug(f"Using cached peaks for {item_path}")
        return peaksCache[cache_key]
    result = await audio_peaks(item_path)
    peaksCache[cache_key] = result
    return result


async def audio_peaks(path: str):
    ffmpeg_streamer = FFmpegStreamer()
    # fmt: off
    await ffmpeg_streamer.start(*[
        "-hide_banner", "-loglevel", "error",
        "-i", str(path), "-ac", "1", "-filter:a", "aresample=8000",
        "-map", "0:a", "-c:a", "pcm_s16le", "-f", "data", "-",
    ])
    # fmt: on
    raw_samples = b"".join([chunk async for chunk in ffmpeg_streamer.stream()])
    samples = np.frombuffer(raw_samples, dtype=np.int16).astype(np.float32) / 32768.0
    window_size = 2056
    starts = np.arange(0, samples.shape[0], window_size)
    return np.maximum.reduceat(samples, starts, dtype=np.float32)


# ─── Routes ──────────────────────────────────────────────────────────────────


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
