from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote

import aiohttp
from thefuzz import fuzz

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


def _parse_duration_seconds(value: Any) -> int:
    """Parse duration to seconds. Handles int seconds, float, and 'MM:SS' / 'HH:MM:SS' strings."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    s = str(value).strip()
    if ":" in s:
        parts = s.split(":")
        try:
            parts_int = [int(p) for p in parts]
            if len(parts_int) == 2:
                return parts_int[0] * 60 + parts_int[1]
            if len(parts_int) == 3:
                return parts_int[0] * 3600 + parts_int[1] * 60 + parts_int[2]
        except ValueError:
            pass
    try:
        return max(0, int(float(s)))
    except ValueError:
        return 0


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
    length_seconds = _parse_duration_seconds(file_entry.get("length"))
    if size_bytes <= 0 or length_seconds <= 0:
        return None

    return (size_bytes * 8.0) / length_seconds / 1000.0


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


def _audio_file_entries(candidate: dict[str, Any]) -> list[tuple[str, float]]:
    """Return (normalised_basename, duration_seconds) for each audio file in candidate."""
    entries: list[tuple[str, float]] = []
    for f in candidate.get("files") or []:
        if not _is_audio_file(str(f.get("extension") or "")):
            continue
        fname = str(f.get("filename") or "")
        base = fname.replace("\\", "/").rsplit("/", 1)[-1]
        base = base.rsplit(".", 1)[0] if "." in base else base
        base = re.sub(r"^\d{1,3}[\s.\-]+", "", base).strip()
        if base:
            entries.append((_norm_text(base), float(_parse_duration_seconds(f.get("length")))))
    return entries


def score_candidate(
    candidate: dict[str, Any],
    *,
    artist_hint: str = "",
    album_hint: str = "",
    expected_track_count: int | None = None,
    expected_tracks: list[dict[str, Any]] | None = None,
    speed_min_bps: int = 1_000_000,
    queue_max: int = 100,
) -> float:
    """Score a candidate. Returns 0.0 to exclude (fewer than half expected tracks).

    D = 0.30*d_folder + 0.25*d_tracks + 0.15*d_duration + 0.15*d_count
        + 0.08*d_speed + 0.07*d_queue   (lower D = better match)
    score = 1 - D
    """
    if expected_track_count:
        audio_count = _safe_int(candidate.get("audioFileCount"))
        if audio_count < expected_track_count / 2:
            return 0.0

    # d_folder: token_sort_ratio handles "Album - Artist" inversions
    query = _norm_text(f"{artist_hint} {album_hint}".strip()) or None
    folder = str(candidate.get("folder") or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    s_folder = fuzz.token_sort_ratio(_norm_text(folder), query) / 100.0 if query else 0.5
    d_folder = 1.0 - s_folder

    # d_tracks + d_duration: for each expected track, find best name-match in result files,
    # then compare duration of that matched file.
    result_entries = _audio_file_entries(candidate)
    if expected_tracks and result_entries:
        name_scores: list[float] = []
        dur_errors: list[float] = []
        for t in expected_tracks:
            exp_title = _norm_text(str(t.get("title") or ""))
            if not exp_title:
                continue
            best_score, best_dur = 0, 0.0
            for rb, rdur in result_entries:
                s = fuzz.token_set_ratio(exp_title, rb)
                if s > best_score:
                    best_score, best_dur = s, rdur
            name_scores.append(best_score / 100.0)
            exp_dur = t.get("duration")
            if exp_dur and exp_dur > 0 and best_dur > 0:
                dur_errors.append(min(abs(exp_dur - best_dur) / max(float(exp_dur), 30.0), 1.0))
        d_tracks = 1.0 - (sum(name_scores) / len(name_scores)) if name_scores else 0.0
        d_duration = sum(dur_errors) / len(dur_errors) if dur_errors else 0.0
    else:
        d_tracks = 0.0
        d_duration = 0.0

    # d_count
    N_a = expected_track_count
    N_r = _safe_int(candidate.get("audioFileCount"))
    d_count = min(abs(N_r - N_a) / N_a, 1.0) if N_a else 0.0

    # d_speed: penalise upload speed below speed_min_bps
    upload_speed = _safe_int(candidate.get("uploadSpeed"))
    d_speed = max(0.0, 1.0 - upload_speed / max(speed_min_bps, 1)) if speed_min_bps > 0 else 0.0
    d_speed = min(d_speed, 1.0)

    # d_queue: penalise queue length above queue_max
    queue_len = _safe_int(candidate.get("queueLength"))
    d_queue = min(1.0, max(0.0, queue_len - queue_max) / max(queue_max, 1)) if queue_max >= 0 else 0.0

    D = (0.25 * d_folder + 0.30 * d_tracks + 0.15 * d_duration
         + 0.15 * d_count + 0.08 * d_speed + 0.07 * d_queue)
    return 1.0 - D


def rank_candidates(
    candidates: list[dict[str, Any]],
    *,
    artist_hint: str = "",
    album_hint: str = "",
    expected_track_count: int | None = None,
    expected_tracks: list[dict[str, Any]] | None = None,
    speed_min_bps: int = 1_000_000,
    queue_max: int = 100,
) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for c in candidates:
        s = score_candidate(
            c,
            artist_hint=artist_hint,
            album_hint=album_hint,
            expected_track_count=expected_track_count,
            expected_tracks=expected_tracks,
            speed_min_bps=speed_min_bps,
            queue_max=queue_max,
        )
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

    # create_timeout scales with the caller's budget so a busy event loop
    # (many concurrent HTTP requests in the same process) doesn't fire before
    # the coroutine has had a chance to run.
    create_timeout = aiohttp.ClientTimeout(total=max(20, timeout_seconds))
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
        del_url = status_url

        poll_timeout = aiohttp.ClientTimeout(total=10)
        # Each poll sleeps 2s; cap total wall time to timeout_seconds
        max_polls = max(4, timeout_seconds // 2)
        completed = False
        result: list[dict[str, Any]] = []
        timed_out = True

        try:
            for attempt in range(max_polls):
                await asyncio.sleep(2)
                try:
                    async with session.get(status_url, timeout=poll_timeout) as r:
                        status_body = await r.json(content_type=None)
                    if not isinstance(status_body, dict):
                        continue
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
                            result = candidates
                            timed_out = False
                            break
                        # responses endpoint returned empty despite rc > 0 — keep polling
                        log.debug("slskd responses not ready yet (rc=%d but got empty list)", rc)
                    # If completed but rc==0, no point polling further
                    if completed:
                        log.info("slskd search completed with rc=0 for %r", query)
                        timed_out = False
                        break
                except Exception as exc:
                    log.warning("slskd poll error: %s", exc)
        finally:
            # Always delete the search to free the concurrent-search slot before returning.
            try:
                async with session.delete(del_url, timeout=aiohttp.ClientTimeout(total=5)):
                    pass
            except Exception:
                pass

    if timed_out:
        log.warning("slskd search timed out for %r", query)
    return result


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
