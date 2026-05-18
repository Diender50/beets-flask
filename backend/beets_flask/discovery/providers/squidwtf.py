from __future__ import annotations

import asyncio
import base64
import difflib
import hashlib
import json
import re
import unicodedata
from pathlib import Path
import time
from typing import Any
from urllib.parse import quote

import aiohttp
from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TPE1, TPE2, TALB, TRCK

from beets_flask.logger import log


def _norm_text(value: str) -> str:
    return (value or "").casefold().strip()


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm_text(a), _norm_text(b)).ratio()


def _safe_int(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        return 0


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "unknown"


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _quality_to_ext(quality: str) -> str:
    q = str(quality or "").strip().upper()
    if q in {"5", "MP3", "MP3_320"}:
        return ".mp3"
    return ".flac"


def _solve_altcha(parameters: dict[str, Any], max_iterations: int = 1_000_000) -> tuple[int, str, int]:
    nonce = bytes.fromhex(str(parameters.get("nonce") or ""))
    salt = bytes.fromhex(str(parameters.get("salt") or ""))
    key_prefix = bytes.fromhex(str(parameters.get("keyPrefix") or ""))
    cost = int(parameters.get("cost") or 0)
    key_length = int(parameters.get("keyLength") or 0)

    if not nonce or not salt or not key_prefix or cost <= 0 or key_length <= 0:
        raise ValueError("invalid altcha challenge parameters")

    started = time.perf_counter()
    for counter in range(max_iterations):
        password = nonce + counter.to_bytes(4, byteorder="big", signed=False)
        derived = hashlib.sha256(salt + password).digest()[:key_length]
        for _ in range(1, cost):
            derived = hashlib.sha256(derived).digest()[:key_length]
        if derived[: len(key_prefix)] == key_prefix:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return counter, derived.hex(), elapsed_ms

    raise RuntimeError("altcha solver exhausted max iterations")


async def _get_captcha_cookie(
    *,
    session: aiohttp.ClientSession,
    base_url: str,
) -> str | None:
    challenge_url = f"{base_url.rstrip('/')}/api/altcha/challenge"
    verify_url = f"{base_url.rstrip('/')}/api/altcha/verify"

    async with session.get(challenge_url) as resp:
        if resp.status != 200:
            log.warning("squidwtf captcha challenge failed status=%s", resp.status)
            return None
        challenge = await resp.json(content_type=None)

    parameters = (challenge or {}).get("parameters")
    if not isinstance(parameters, dict):
        log.warning("squidwtf captcha challenge missing parameters")
        return None

    counter, derived_key, elapsed_ms = await asyncio.to_thread(_solve_altcha, parameters)
    solution = {"counter": counter, "derivedKey": derived_key, "time": elapsed_ms}
    payload_json = json.dumps({"challenge": challenge, "solution": solution}, separators=(",", ":"))
    payload_b64 = base64.b64encode(payload_json.encode("utf-8")).decode("ascii")

    async with session.post(verify_url, json={"payload": payload_b64}) as resp:
        if resp.status < 200 or resp.status >= 300:
            body = await resp.text()
            log.warning("squidwtf captcha verify failed status=%s body=%s", resp.status, body[:180])
            return None

        set_cookies = resp.headers.getall("Set-Cookie", [])
        for raw in set_cookies:
            token = raw.split(";", 1)[0].strip()
            if token.startswith("captcha_verified_at="):
                return token

    log.warning("squidwtf captcha verify succeeded but no captcha cookie found")
    return None


async def resolve_squidwtf_match_for_album(
    *,
    artist: str,
    album: str,
    timeout_seconds: int = 15,
    base_url: str = "https://qobuz.squid.wtf",
) -> dict[str, Any] | None:
    if not artist.strip() and not album.strip():
        return None

    query = f"{artist} {album}".strip()
    artist_norm = _strip_accents(artist)
    album_norm = _strip_accents(album)
    query_candidates = [query]
    norm_query = f"{artist_norm} {album_norm}".strip()
    if norm_query and norm_query != query:
        query_candidates.append(norm_query)

    # Keep each network call short and retry to avoid long single-shot timeouts.
    per_attempt_timeout = max(4, min(12, timeout_seconds // 2 if timeout_seconds > 1 else 4))
    timeout = aiohttp.ClientTimeout(total=per_attempt_timeout)
    headers = {"Token-Country": "US"}

    best: dict[str, Any] | None = None
    best_score = -1.0

    payload: dict[str, Any] | None = None
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        for q in query_candidates:
            url = f"{base_url.rstrip('/')}/api/get-music?q={quote(q)}&offset=0"
            for attempt in range(2):
                try:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            log.warning(
                                "squidwtf search status=%s query=%r attempt=%d",
                                resp.status,
                                q,
                                attempt + 1,
                            )
                            break
                        payload = await resp.json(content_type=None)
                        break
                except TimeoutError:
                    log.warning(
                        "squidwtf search timeout query=%r attempt=%d timeout=%ss",
                        q,
                        attempt + 1,
                        per_attempt_timeout,
                    )
                    if attempt == 0:
                        await asyncio.sleep(0.4)
                except Exception as exc:
                    log.warning("squidwtf search failed query=%r attempt=%d err=%r", q, attempt + 1, exc)
                    break

            if payload is not None:
                break

    if payload is None:
        return None

    for item in ((payload.get("data") or {}).get("albums") or {}).get("items") or []:
        title = str(item.get("title") or "")
        item_artist = str((item.get("artist") or {}).get("name") or "")
        score = _similarity(title, album) * 0.7 + _similarity(item_artist, artist) * 0.3
        if score > best_score:
            best_score = score
            album_id = item.get("id")
            if album_id is None:
                continue
            best = {
                "provider": "squidwtf",
                "squid_album_id": str(album_id),
                "title": title,
                "artist": item_artist,
                "score": score,
                "track_count": item.get("tracks_count"),
            }

    return best


async def download_album(
    *,
    base_url: str,
    album_id: str,
    output_path: str,
    quality: str,
    timeout_seconds: int = 45,
) -> tuple[bool, str | None]:
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    headers = {"Token-Country": "US"}
    album_url = f"{base_url.rstrip('/')}/api/get-album?album_id={quote(str(album_id))}"

    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(album_url) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return (False, f"squidwtf album fetch failed ({resp.status}): {text[:220]}")
                payload = await resp.json(content_type=None)

            album = (payload.get("data") or {})
            title = _safe_filename(str(album.get("title") or "Unknown Album"))
            artist = _safe_filename(str((album.get("artist") or {}).get("name") or "Unknown Artist"))
            tracks = ((album.get("tracks") or {}).get("items") or [])
            if not tracks:
                return (False, "squidwtf album has no tracks")

            target_dir = Path(output_path) / artist / title
            target_dir.mkdir(parents=True, exist_ok=True)
            extension = _quality_to_ext(quality)

            # Solve captcha upfront — download endpoint returns 403 (not 200) when
            # no valid captcha cookie is present, so lazy detection never fires.
            captcha_cookie = await _get_captcha_cookie(session=session, base_url=base_url)
            if captcha_cookie:
                log.debug("squidwtf captcha cookie obtained")
            else:
                log.warning("squidwtf could not obtain captcha cookie, downloads may fail")

            media_timeout = aiohttp.ClientTimeout(total=300)
            success_count = 0
            for idx, track in enumerate(tracks, start=1):
                track_id = track.get("id")
                if track_id is None:
                    continue
                dl_url = f"{base_url.rstrip('/')}/api/download-music?track_id={quote(str(track_id))}&quality={quote(str(quality))}"
                # Session cookie jar holds captcha_verified_at after _get_captcha_cookie;
                # pass it explicitly as well for robustness.
                dl_headers: dict[str, str] = {"Cookie": captcha_cookie} if captcha_cookie else {}
                async with session.get(dl_url, headers=dl_headers or None) as dl_resp:
                    if dl_resp.status not in (200, 403):
                        log.debug("squidwtf track %d/%d status=%s, skipping", idx, len(tracks), dl_resp.status)
                        continue
                    dl_payload = await dl_resp.json(content_type=None)

                if isinstance(dl_payload, dict) and dl_payload.get("success") is False:
                    err = str(dl_payload.get("error") or "")
                    if "captcha" in err.casefold():
                        # Cookie may have expired — refresh and retry once.
                        log.debug("squidwtf captcha required for track %d, refreshing cookie", idx)
                        captcha_cookie = await _get_captcha_cookie(session=session, base_url=base_url)
                        if captcha_cookie:
                            async with session.get(dl_url, headers={"Cookie": captcha_cookie}) as retry_resp:
                                if retry_resp.status == 200:
                                    dl_payload = await retry_resp.json(content_type=None)

                if isinstance(dl_payload, dict) and dl_payload.get("success") is False:
                    log.debug("squidwtf track %d/%d failed: %s", idx, len(tracks), dl_payload.get("error"))
                    continue

                media_url = (((dl_payload.get("data") or {}).get("url")) if isinstance(dl_payload, dict) else None)
                if not media_url:
                    log.debug("squidwtf track %d/%d no media url in payload", idx, len(tracks))
                    continue

                track_title = _safe_filename(str(track.get("title") or f"Track {idx:02d}"))
                filename = f"{idx:02d} - {track_title}{extension}"
                file_path = target_dir / filename

                async with session.get(str(media_url), timeout=media_timeout) as media_resp:
                    if media_resp.status != 200:
                        log.debug("squidwtf track %d/%d media fetch status=%s", idx, len(tracks), media_resp.status)
                        continue
                    with file_path.open("wb") as fp:
                        async for chunk in media_resp.content.iter_chunked(128 * 1024):
                            if chunk:
                                fp.write(chunk)
                track_title_raw = str(track.get("title") or f"Track {idx:02d}")
                track_artist = str(
                    (track.get("performer") or {}).get("name")
                    or (track.get("artist") or {}).get("name")
                    or artist
                )
                _tag_file(
                    file_path,
                    title=track_title_raw,
                    artist=track_artist,
                    albumartist=artist,
                    album=title,
                    track_num=idx,
                    track_total=len(tracks),
                )
                log.debug("squidwtf track %d/%d downloaded: %s", idx, len(tracks), filename)
                success_count += 1

            if success_count <= 0:
                return (False, "squidwtf download produced no files")
            return (True, f"downloaded {success_count}/{len(tracks)} tracks")
    except Exception as exc:
        log.exception("squidwtf download failed album_id=%s", album_id)
        return (False, str(exc))


def _tag_file(
    file_path: Path,
    *,
    title: str,
    artist: str,
    albumartist: str,
    album: str,
    track_num: int,
    track_total: int,
) -> None:
    """Write basic tags to a downloaded FLAC or MP3 file."""
    ext = file_path.suffix.lower()
    try:
        if ext == ".flac":
            audio = FLAC(str(file_path))
            audio["title"] = title
            audio["artist"] = artist
            audio["albumartist"] = albumartist
            audio["album"] = album
            audio["tracknumber"] = str(track_num)
            audio["tracktotal"] = str(track_total)
            audio.save()
        elif ext == ".mp3":
            try:
                audio_id3 = ID3(str(file_path))
            except ID3NoHeaderError:
                audio_id3 = ID3()
            audio_id3["TIT2"] = TIT2(encoding=3, text=title)
            audio_id3["TPE1"] = TPE1(encoding=3, text=artist)
            audio_id3["TPE2"] = TPE2(encoding=3, text=albumartist)
            audio_id3["TALB"] = TALB(encoding=3, text=album)
            audio_id3["TRCK"] = TRCK(encoding=3, text=f"{track_num}/{track_total}")
            audio_id3.save(str(file_path))
    except Exception as exc:
        log.warning("squidwtf tagging failed for %s: %r", file_path.name, exc)


def quality_label_to_display(quality: str) -> dict[str, Any]:
    q = str(quality or "").strip().upper()
    if q == "27":
        return {"container": "FLAC", "kbps": 2000}
    if q in {"7", "6"}:
        return {"container": "FLAC", "kbps": 1411}
    if q in {"5", "MP3", "MP3_320"}:
        return {"container": "MP3", "kbps": 320}
    return {"container": "FLAC", "kbps": None}
