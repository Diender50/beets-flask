from __future__ import annotations

import asyncio
import difflib
import unicodedata
import json
from typing import Any
from urllib.parse import quote

import aiohttp

from beets_flask.logger import log


def _norm_text(value: str) -> str:
    return (value or "").casefold().strip()


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm_text(a), _norm_text(b)).ratio()


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _quality_label_from_detail(detail: dict[str, Any]) -> str | None:
    # Best effort: Deezer payloads vary; use first quality-related field we can find.
    for key in ("quality", "audio_quality", "format", "audio_format"):
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for key in ("available_formats", "formats", "qualities"):
        value = detail.get(key)
        if isinstance(value, list):
            labels = [str(v).strip() for v in value if str(v).strip()]
            if labels:
                return " / ".join(labels)
        if isinstance(value, dict):
            labels = [str(k).strip() for k, enabled in value.items() if enabled and str(k).strip()]
            if labels:
                return " / ".join(labels)

    return None


def _quality_parts_from_label(label: str | None) -> tuple[str | None, int | None]:
    if not label:
        return (None, None)

    q = str(label).casefold()
    if "flac" in q or "lossless" in q:
        return ("FLAC", 1411)
    if "320" in q:
        return ("MP3", 320)
    if "256" in q:
        if "aac" in q or "m4a" in q:
            return ("AAC", 256)
        return ("MP3", 256)
    if "128" in q:
        return ("MP3", 128)
    if "opus" in q:
        return ("OPUS", None)
    if "aac" in q or "m4a" in q:
        return ("AAC", None)
    if "mp3" in q:
        return ("MP3", None)
    return (None, None)


def _collect_strings(node: Any, out: list[str]) -> None:
    if isinstance(node, str):
        out.append(node)
        return
    if isinstance(node, dict):
        for k, v in node.items():
            out.append(str(k))
            _collect_strings(v, out)
        return
    if isinstance(node, list):
        for v in node:
            _collect_strings(v, out)


def _quality_from_max_bitrate(value: Any) -> dict[str, Any] | None:
    code = str(value or "").strip().casefold()
    # deemix maxBitrate common codes
    if code in {"9", "flac", "lossless"}:
        return {"container": "FLAC", "kbps": 1411}
    if code in {"3", "320", "mp3_320"}:
        return {"container": "MP3", "kbps": 320}
    if code in {"1", "128", "mp3_128", "0"}:
        return {"container": "MP3", "kbps": 128}
    if code in {"15", "aac_256", "m4a_256", "256"}:
        return {"container": "AAC", "kbps": 256}
    return None


async def resolve_quality_from_arl(
    *,
    base_url: str,
    timeout_seconds: int = 12,
    auth_header: str | None = None,
    arl: str | None = None,
) -> dict[str, Any] | None:
    """Resolve deemix output quality from deemix session settings and account hints."""
    if not base_url:
        return None

    headers: dict[str, str] = {}
    if auth_header:
        headers["Authorization"] = auth_header

    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        if arl:
            try:
                login_url = f"{base_url.rstrip('/')}/api/loginArl"
                async with session.post(login_url, json={"arl": arl}):
                    pass
            except Exception:
                return None

        settings_payload: dict[str, Any] | None = None
        settings_url = f"{base_url.rstrip('/')}/api/getSettings"
        try:
            async with session.get(settings_url) as resp:
                if resp.status == 200:
                    settings_payload = await resp.json(content_type=None)
        except Exception:
            settings_payload = None

        if isinstance(settings_payload, dict):
            settings = settings_payload.get("settings") if isinstance(settings_payload.get("settings"), dict) else settings_payload
            inferred = _quality_from_max_bitrate((settings or {}).get("maxBitrate"))
            if inferred is not None:
                return inferred

        # Fallback for deemix builds exposing user/account info but no settings format.
        user_data_url = f"{base_url.rstrip('/')}/api/getUserData"
        try:
            async with session.get(user_data_url) as resp:
                if resp.status != 200:
                    return None
                payload = await resp.json(content_type=None)
        except Exception:
            return None

    tokens: list[str] = []
    _collect_strings(payload, tokens)
    corpus = " ".join(t.casefold() for t in tokens if t)

    if "deezer free" in corpus or " free" in corpus:
        return {"container": "MP3", "kbps": 128}
    if "hifi" in corpus or "flac" in corpus or "lossless" in corpus:
        return {"container": "FLAC", "kbps": 1411}
    if "premium" in corpus:
        return {"container": "MP3", "kbps": 320}
    return None


async def resolve_deezer_id_for_album(artist: str, album: str, timeout_seconds: int = 12) -> str | None:
    """Resolve a Deezer album id from artist/album text using Deezer public API.

    This is used as deemix input for non-deezer release IDs.
    """
    match = await resolve_deezer_match_for_album(artist=artist, album=album, timeout_seconds=timeout_seconds)
    return match["deezer_id"] if match else None


async def resolve_deezer_match_for_album(
    artist: str,
    album: str,
    timeout_seconds: int = 12,
) -> dict[str, Any] | None:
    """Resolve best Deezer album match from artist/album text.

    Returns the best album plus similarity score so callers can compare it with other providers.
    """
    if not artist.strip() and not album.strip():
        return None

    artist_norm = _strip_accents(artist)
    album_norm = _strip_accents(album)
    query_candidates = [
        f'artist:"{artist}" album:"{album}"'.strip(),
        f"{artist} {album}".strip(),
    ]
    if (artist_norm, album_norm) != (artist, album):
        query_candidates.extend([
            f'artist:"{artist_norm}" album:"{album_norm}"'.strip(),
            f"{artist_norm} {album_norm}".strip(),
        ])

    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    best_match: dict[str, Any] | None = None
    best_score = -1.0

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for query in query_candidates:
            if not query:
                continue
            url = f"https://api.deezer.com/search/album?q={quote(query)}&limit=25"
            data: dict[str, Any] | None = None

            # Short retry for transient Deezer hiccups.
            for attempt in range(2):
                try:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            log.warning("deemix Deezer search status=%s query=%r", resp.status, query)
                            break
                        data = await resp.json(content_type=None)
                        break
                except Exception as exc:
                    log.warning("deemix Deezer search failed attempt=%d query=%r err=%r", attempt + 1, query, exc)
                    await asyncio.sleep(0.35)

            if not data:
                continue

            for row in data.get("data", []):
                candidate_title = str(row.get("title", ""))
                candidate_artist = str((row.get("artist") or {}).get("name", ""))
                score = _similarity(candidate_title, album) * 0.7 + _similarity(candidate_artist, artist) * 0.3
                if score > best_score:
                    best_score = score
                    cand_id = row.get("id")
                    if cand_id:
                        best_match = {
                            "provider": "deemix",
                            "deezer_id": str(cand_id),
                            "title": candidate_title,
                            "artist": candidate_artist,
                            "score": score,
                        }

            if best_score >= 0.98:
                break

        if best_match and best_match.get("deezer_id"):
            try:
                details_url = f"https://api.deezer.com/album/{quote(str(best_match['deezer_id']))}"
                async with session.get(details_url) as resp:
                    if resp.status == 200:
                        detail = await resp.json(content_type=None)
                        nb_tracks = detail.get("nb_tracks")
                        if nb_tracks is not None:
                            best_match["track_count"] = nb_tracks
                        quality = _quality_label_from_detail(detail)
                        if quality:
                            best_match["quality"] = quality
                            container, kbps = _quality_parts_from_label(quality)
                            if container:
                                best_match["container"] = container
                            if kbps is not None:
                                best_match["kbps"] = kbps
            except Exception as exc:
                log.warning("deemix Deezer detail failed id=%s err=%r", best_match.get("deezer_id"), exc)

    return best_match


async def enqueue_download(
    *,
    base_url: str,
    deezer_id: str,
    output_path: str,
    timeout_seconds: int = 20,
    auth_header: str | None = None,
    arl: str | None = None,
    bitrate: str = "1",
) -> tuple[bool, str | None]:
    """Request deemix GUI service to download album by deezer id.

    Uses the deemix GUI server's addToQueue endpoint.
    POST {base_url}/api/addToQueue
    Body: {url, bitrate}

    When ``arl`` is provided, calls /api/loginArl first in the same session so
    the session cookie is valid for the queue call.  This is needed when deemix
    is NOT running in DEEMIX_SINGLE_USER mode (i.e. ARL env var not set on the
    container).
    """
    if not base_url:
        return (False, "deemix base_url not configured")

    headers: dict[str, str] = {}
    if auth_header:
        headers["Authorization"] = auth_header

    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        # Ensure we are logged in if an ARL is configured.
        if arl:
            login_url = f"{base_url.rstrip('/')}/api/loginArl"
            try:
                async with session.post(login_url, json={"arl": arl}) as lr:
                    login_body = await lr.json(content_type=None)
                    if login_body.get("status") not in (1, True):
                        log.warning("deemix loginArl status=%s", login_body.get("status"))
            except Exception as exc:
                log.warning("deemix loginArl failed: %r", exc)

        queue_url = f"{base_url.rstrip('/')}/api/addToQueue"
        payload: dict[str, Any] = {
            "url": f"https://www.deezer.com/album/{deezer_id}",
            "bitrate": str(bitrate or "1"),
        }
        async with session.post(queue_url, json=payload) as resp:
            text = await resp.text()
            if 200 <= resp.status < 300:
                # deemix may return HTTP 200 with {"result": false, "errid": ...}
                try:
                    body = json.loads(text) if text else None
                except Exception:
                    body = None

                if isinstance(body, dict):
                    result_flag = body.get("result")
                    if result_flag is False:
                        errid = body.get("errid")
                        return (False, f"deemix enqueue rejected: {errid or body}")
                return (True, text or None)
            return (False, f"deemix enqueue failed ({resp.status}): {text[:300]}")
