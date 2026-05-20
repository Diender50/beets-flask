from __future__ import annotations

import asyncio
import difflib
import re
from typing import Any
from urllib.parse import quote

import aiohttp

from beets_flask.logger import log


def _norm_text(value: str) -> str:
    return (value or "").casefold().strip()


def _safe_int(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        return 0


_AUDIO_EXTENSIONS = {
    "flac",
    "mp3",
    "m4a",
    "aac",
    "opus",
    "ogg",
    "oga",
    "wav",
    "aiff",
    "aif",
    "alac",
    "wma",
    "ape",
    "mpc",
    "wv",
    "tta",
}


def _is_audio_file(extension: str) -> bool:
    return str(extension or "").casefold().lstrip(".") in _AUDIO_EXTENSIONS


def _file_extension(filename: str, extension: str | None = None) -> str:
    ext = str(extension or "").casefold().lstrip(".")
    if ext:
        return ext

    normalized = str(filename or "").replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1]
    if "." not in basename:
        return ""
    return basename.rsplit(".", 1)[-1].casefold().strip()


def _estimate_kbps(file_entry: dict[str, Any]) -> float | None:
    bitrate = file_entry.get("bitRate") or file_entry.get("bitrate") or file_entry.get("kbps")
    if bitrate is not None:
        try:
            value = float(bitrate)
            if value > 0:
                return value
        except Exception:
            pass

    size_bytes = _safe_int(file_entry.get("size"))
    length_seconds = _safe_int(file_entry.get("length"))
    if size_bytes <= 0 or length_seconds <= 0:
        return None

    return (size_bytes * 8.0) / max(length_seconds, 1) / 1000.0


def _audio_quality_score(extension: str, sample_rate: int, bit_depth: int) -> float:
    """Score audio quality from slskd file metadata (no bitrate field available)."""
    ext = extension.casefold().lstrip(".")
    if ext == "flac":
        if sample_rate >= 88200 or bit_depth >= 24:
            return 1.0
        return 0.95
    if ext in ("wav", "aiff", "aif"):
        return 0.9
    if ext == "mp3":
        return 0.65
    if ext in ("aac", "m4a", "ogg", "opus"):
        return 0.6
    if ext in ("wma",):
        return 0.4
    return 0.3


def _flatten_responses(user_responses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group slskd user-level responses into per-album candidate dicts.

    slskd /searches/{id}/responses returns:
      [{ username, uploadSpeed, hasFreeUploadSlot, queueLength, files: [...] }, ...]
    Each file: { filename, extension, size, length, sampleRate, bitDepth, ... }

    Files are grouped by (username, parent_directory) to produce album-level candidates.
    Each candidate contains a 'files' list for bulk enqueue.
    """
    # album_key -> album candidate dict
    albums: dict[tuple[str, str], dict[str, Any]] = {}

    for response in user_responses:
        if not isinstance(response, dict):
            continue
        username = response.get("username", "")
        upload_speed = _safe_int(response.get("uploadSpeed"))
        has_slot = bool(response.get("hasFreeUploadSlot"))
        queue_len = _safe_int(response.get("queueLength"))

        for f in response.get("files", []):
            if not isinstance(f, dict):
                continue
            if f.get("isLocked"):
                continue

            filename = f.get("filename", "")
            # Normalize path separator and get parent folder
            norm_filename = filename.replace("\\", "/")
            parent_dir = norm_filename.rsplit("/", 1)[0] if "/" in norm_filename else ""
            album_key = (username, parent_dir)

            if album_key not in albums:
                albums[album_key] = {
                    "username": username,
                    "uploadSpeed": upload_speed,
                    "hasFreeUploadSlot": has_slot,
                    "queueLength": queue_len,
                    "folder": parent_dir,
                    "files": [],
                    # best quality fields (updated as we see more files)
                    "extension": "",
                    "sampleRate": 0,
                    "bitDepth": 0,
                    "totalSize": 0,
                    "audioFileCount": 0,
                    "meanAudioBitrateKbps": None,
                    "_audioBitrateSum": 0.0,
                    "_audioBitrateCount": 0,
                }

            album = albums[album_key]
            file_extension = _file_extension(filename, f.get("extension"))
            file_entry = {
                "filename": filename,
                "extension": file_extension,
                "size": f.get("size"),
                "length": f.get("length"),
                "sampleRate": f.get("sampleRate"),
                "bitDepth": f.get("bitDepth"),
            }
            album["files"].append(file_entry)
            album["totalSize"] = (album["totalSize"] or 0) + (_safe_int(f.get("size")))

            is_audio_file = _is_audio_file(file_entry["extension"])
            if is_audio_file:
                album["audioFileCount"] = _safe_int(album.get("audioFileCount")) + 1
                kbps = _estimate_kbps(file_entry)
                if kbps is not None:
                    album["_audioBitrateSum"] = float(album.get("_audioBitrateSum") or 0.0) + kbps
                    album["_audioBitrateCount"] = _safe_int(album.get("_audioBitrateCount")) + 1
                    album["meanAudioBitrateKbps"] = (
                        float(album["_audioBitrateSum"]) / _safe_int(album["_audioBitrateCount"])
                    )

            # Track best quality metadata from audio files only.
            if is_audio_file:
                ext = file_entry["extension"]
                sr = _safe_int(f.get("sampleRate"))
                bd = _safe_int(f.get("bitDepth"))
                cur_q = _audio_quality_score(album["extension"], _safe_int(album["sampleRate"]), _safe_int(album["bitDepth"]))
                new_q = _audio_quality_score(ext, sr, bd)
                if new_q > cur_q:
                    album["extension"] = ext
                    album["sampleRate"] = sr
                    album["bitDepth"] = bd

    flattened = list(albums.values())
    for album in flattened:
        album.pop("_audioBitrateSum", None)
        album.pop("_audioBitrateCount", None)
    return flattened


def _folder_match_score(candidate: dict[str, Any], album_hint: str) -> float:
    """Score how well the folder name and audio filenames match the searched album."""
    if not album_hint:
        return 0.5  # neutral when no hint

    album_norm = _norm_text(album_hint)
    folder = str(candidate.get("folder") or "")
    folder_basename = folder.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    folder_score = difflib.SequenceMatcher(None, _norm_text(folder_basename), album_norm).ratio()

    # Also check filenames: strip leading "NN - " / "NN." track number prefix then compare
    files: list[dict[str, Any]] = candidate.get("files") or []
    audio_exts = {".flac", ".mp3", ".m4a", ".ogg", ".aac", ".wav", ".aiff", ".opus", ".wma"}
    file_scores: list[float] = []
    for f in files:
        fname = str(f.get("filename") or "")
        ext = ("." + str(f.get("extension") or "")).lower().rstrip(".")
        if ext not in audio_exts:
            continue
        base = fname.replace("\\", "/").rsplit("/", 1)[-1]
        # Strip extension
        base = base.rsplit(".", 1)[0] if "." in base else base
        # Strip leading track number prefix e.g. "01 - ", "01. ", "1 "
        base = re.sub(r"^\d{1,3}[\s.\-]+", "", base).strip()
        if base:
            file_scores.append(difflib.SequenceMatcher(None, _norm_text(base), album_norm).ratio())

    file_avg = sum(file_scores) / len(file_scores) if file_scores else 0.0
    return folder_score * 0.6 + file_avg * 0.4


def score_candidate(
    candidate: dict[str, Any],
    *,
    album_hint: str = "",
    expected_track_count: int | None = None,
) -> float:
    """Score a Soulseek candidate based on speed, queue availability, and filename match.

    Returns 0.0 (excluded from ranking) when the folder has fewer than half the
    expected number of audio tracks.
    """
    if expected_track_count:
        audio_count = _safe_int(candidate.get("audioFileCount"))
        if audio_count < expected_track_count / 2:
            return 0.0

    upload_speed = _safe_int(candidate.get("uploadSpeed"))
    has_slot = bool(candidate.get("hasFreeUploadSlot"))
    queue_len = _safe_int(candidate.get("queueLength"))

    speed_score = min(upload_speed / 10_000_000.0, 1.0)
    # queue=0+slot → 1.0; queue=1 no slot → 0.5; queue=5 → 0.17
    queue_score = 1.0 if has_slot and queue_len == 0 else 1.0 / (1.0 + queue_len)
    name_score = _folder_match_score(candidate, album_hint)

    return speed_score * 0.40 + queue_score * 0.40 + name_score * 0.20


def rank_candidates(
    candidates: list[dict[str, Any]],
    *,
    album_hint: str = "",
    expected_track_count: int | None = None,
) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for c in candidates:
        s = score_candidate(c, album_hint=album_hint, expected_track_count=expected_track_count)
        if s > 0.0:
            scored.append((s, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored]


async def search_album(
    *,
    base_url: str,
    api_key: str | None,
    artist: str,
    album: str,
    timeout_seconds: int = 30,
) -> list[dict[str, Any]]:
    """Search slskd and return a flat list of per-file candidates."""
    if not base_url:
        raise RuntimeError("slskd base_url not configured")

    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key

    query = f"{artist} {album}".strip()
    log.info("slskd search: %r", query)

    create_timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(headers=headers) as session:
        create_url = f"{base_url.rstrip('/')}/api/v0/searches"
        async with session.post(create_url, json={"searchText": query}, timeout=create_timeout) as resp:
            body = await resp.json(content_type=None)
            if resp.status not in (200, 201, 202):
                raise RuntimeError(f"slskd search create failed ({resp.status}): {str(body)[:300]}")

        search_id = body.get("id")
        if not search_id:
            raise RuntimeError("slskd search id missing in response")

        log.info("slskd search id: %s", search_id)
        status_url = f"{base_url.rstrip('/')}/api/v0/searches/{quote(str(search_id))}"
        responses_url = f"{status_url}/responses"

        poll_timeout = aiohttp.ClientTimeout(total=10)
        # Each poll sleeps 2s; cap total wall time to timeout_seconds
        max_polls = max(4, timeout_seconds // 2)
        completed = False
        for attempt in range(max_polls):
            await asyncio.sleep(2)
            try:
                async with session.get(status_url, timeout=poll_timeout) as r:
                    status_body = await r.json(content_type=None)
                state = str(status_body.get("state", ""))
                rc = _safe_int(status_body.get("responseCount"))
                if "Completed" in state or "Stopped" in state or "TimedOut" in state:
                    completed = True
                log.debug(
                    "slskd poll %d/%d state=%s responses=%d completed=%s",
                    attempt + 1, max_polls, state, rc, completed,
                )
                # Fetch as soon as we have any responses — don't wait for search to complete.
                # Partial results (search still running) are far better than timing out with 0.
                if rc and rc > 0:
                    async with session.get(responses_url, timeout=poll_timeout) as r2:
                        user_responses = await r2.json(content_type=None)
                    if isinstance(user_responses, list) and user_responses:
                        candidates = _flatten_responses(user_responses)
                        for candidate in candidates:
                            if isinstance(candidate, dict):
                                candidate["searchId"] = str(search_id)
                        log.info(
                            "slskd search %s: rc=%d -> %d candidates",
                            "completed" if completed else "partial",
                            rc, len(candidates),
                        )
                        return candidates
                    # responses endpoint returned empty despite rc > 0 — keep polling
                    log.debug("slskd responses not ready yet (rc=%d but got empty list)", rc)
                # If completed but rc==0, no point polling further
                if completed:
                    log.info("slskd search completed with rc=0 for %r", query)
                    return []
            except Exception as exc:
                log.warning("slskd poll error: %s", exc)

    log.warning("slskd search timed out for %r", query)
    return []


async def delete_search(
    *,
    base_url: str,
    api_key: str | None,
    search_id: str,
    timeout_seconds: int = 10,
) -> bool:
    if not base_url or not search_id:
        return False

    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key

    url = f"{base_url.rstrip('/')}/api/v0/searches/{quote(str(search_id))}"
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.delete(url) as resp:
                if 200 <= resp.status < 300 or resp.status == 404:
                    return True
                log.warning("slskd delete search %s failed (%d)", search_id, resp.status)
                return False
    except Exception as exc:
        log.warning("slskd delete search %s error: %s", search_id, exc)
        return False


async def delete_searches_for_query(
    *,
    base_url: str,
    api_key: str | None,
    artist: str,
    album: str,
    timeout_seconds: int = 12,
    search_ids: list[str] | None = None,
) -> int:
    if not base_url:
        return 0

    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key

    query = f"{artist} {album}".strip().casefold()
    ids_to_delete: set[str] = {str(s).strip() for s in (search_ids or []) if str(s).strip()}
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    list_url = f"{base_url.rstrip('/')}/api/v0/searches"

    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(list_url) as resp:
                if 200 <= resp.status < 300:
                    body = await resp.json(content_type=None)
                    if isinstance(body, list):
                        for entry in body:
                            if not isinstance(entry, dict):
                                continue
                            sid = str(entry.get("id") or "").strip()
                            if not sid:
                                continue
                            search_text = str(entry.get("searchText") or "").strip().casefold()
                            if query and search_text == query:
                                ids_to_delete.add(sid)
                else:
                    log.warning("slskd list searches failed (%d)", resp.status)
    except Exception as exc:
        log.warning("slskd list searches error: %s", exc)

    if not ids_to_delete:
        return 0

    deleted = 0
    for sid in ids_to_delete:
        ok = await delete_search(
            base_url=base_url,
            api_key=api_key,
            search_id=sid,
            timeout_seconds=max(5, timeout_seconds // 2),
        )
        if ok:
            deleted += 1
    return deleted


async def enqueue_download(
    *,
    base_url: str,
    api_key: str | None,
    candidate: dict[str, Any],
    output_path: str,
    timeout_seconds: int = 20,
) -> tuple[bool, str | None]:
    """Queue all files from an album candidate via slskd.

    API: POST /api/v0/transfers/downloads/{username}
    Body: [{"filename": "...", "size": N}, ...]
    """
    if not base_url:
        return (False, "slskd base_url not configured")

    username = candidate.get("username") or ""
    files = candidate.get("files") or []

    # Backward compat: single-file candidate (filename at top level)
    if not files and candidate.get("filename"):
        files = [{"filename": candidate["filename"], "size": candidate.get("size")}]

    if not username or not files:
        return (False, f"candidate missing username or files: {candidate}")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    url = f"{base_url.rstrip('/')}/api/v0/transfers/downloads/{quote(username)}"
    body: list[dict[str, Any]] = []
    for f in files:
        entry: dict[str, Any] = {"filename": f["filename"]}
        if f.get("size") is not None:
            entry["size"] = f["size"]
        body.append(entry)

    log.info("slskd enqueue: user=%s files=%d folder=%s", username, len(body), candidate.get("folder", ""))
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.post(url, json=body) as resp:
            text = await resp.text()
            if 200 <= resp.status < 300:
                log.info("slskd enqueue success (%d)", resp.status)
                return (True, text or None)
            log.warning("slskd enqueue failed (%d): %s", resp.status, text[:300])
            return (False, f"slskd enqueue failed ({resp.status}): {text[:300]}")
