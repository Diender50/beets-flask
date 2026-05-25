"""Artist routes."""

import json
import re
import unicodedata
import urllib.parse
import urllib.request
from urllib.parse import urlparse

import musicbrainzngs
import pandas as pd
from fastapi import APIRouter, HTTPException, Response

from beets_flask.config import get_config
from beets_flask.library_cache import (
    ARTISTS_CACHE_PREFIX,
    MISSING_CACHE_PREFIX,
    get_db_missing_cache,
    get_json_cache,
    get_missing_count_map,
    invalidate_artists_cache,
    invalidate_artists_list_cache,
    invalidate_prefix,
    set_db_missing_cache,
    set_json_cache,
)
from beets_flask.logger import log
from beets_flask.server.dependencies import BeetsLib, CurrentUser
from beets_flask.server.exceptions import NotFoundException

ARTIST_SEPARATORS: list[str] = get_config()["gui"]["library"][
    "artist_separators"
].as_str_seq()


def _split_pattern(separators: list[str]) -> str:
    return "|".join(map(re.escape, separators))


split_pattern_artists = _split_pattern(ARTIST_SEPARATORS)

ARTISTS_CACHE_TTL_SECONDS = 300
MISSING_CACHE_TTL_SECONDS = 3600
_MUSICBRAINZ_ID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)

MB_ALIAS_CACHE_PREFIX = "mb_alias:"
MB_ALL_ALIASES_CACHE_PREFIX = "mb_aliases_all:"  # JSON list [primary_first, ...]
MB_NAME_CACHE_PREFIX = "mb_artist_name:"  # keyed by normalized artist name
MB_ALIAS_CACHE_TTL_SECONDS = 86400  # 24 h


def _musicbrainz_api_base_url() -> str:
    try:
        return (
            str(
                get_config()["gui"]["discovery"]["musicbrainz"]["base_url"].get(
                    "https://musicbrainz.org/ws/2"
                )
            )
            .strip()
            .rstrip("/")
        )
    except Exception:
        return "https://musicbrainz.org/ws/2"


def _configure_musicbrainz_client() -> None:
    base_url = _musicbrainz_api_base_url()
    parsed = urlparse(base_url)

    hostname = parsed.netloc or parsed.path
    use_https = parsed.scheme.casefold() != "http"

    if not hostname:
        hostname = "musicbrainz.org"
        use_https = True

    musicbrainzngs.set_hostname(hostname, use_https=use_https)


def _artists_cache_key(artist_name: str | None) -> str:
    return f"{ARTISTS_CACHE_PREFIX}{artist_name or '__all__'}"


def _missing_cache_key(artist_name: str) -> str:
    return f"{MISSING_CACHE_PREFIX}{artist_name}"


def _normalize_artist_name(artist_name: str) -> str:
    return artist_name.strip().casefold()


def _parse_missing_album_line(line: str) -> dict[str, str | int | None] | None:
    line = line.strip()
    if not line:
        return None

    if " - " in line:
        _, album = line.split(" - ", 1)
    else:
        album = line

    return {
        "album": album.strip(),
        "year": None,
        "mb_releasegroupid": None,
    }


def _extract_release_group_year(first_release_date: str | None) -> int | None:
    if not first_release_date:
        return None

    match = re.match(r"^(\d{4})", first_release_date)
    if not match:
        return None

    return int(match.group(1))


def _artist_names_from_item(item) -> list[str]:
    artists = getattr(item, "artists", None)
    if artists:
        return [str(artist).strip() for artist in artists if str(artist).strip()]

    artist = getattr(item, "artist", None)
    if not artist:
        return []

    if ARTIST_SEPARATORS:
        return [
            artist_name.strip()
            for artist_name in re.split(split_pattern_artists, str(artist))
            if artist_name.strip()
        ]

    return [str(artist).strip()]


def _albumartist_names_from_album(album) -> list[str]:
    albumartists = getattr(album, "albumartists", None)
    if albumartists:
        return [str(artist).strip() for artist in albumartists if str(artist).strip()]

    albumartist = getattr(album, "albumartist", None)
    if not albumartist:
        return []

    if ARTIST_SEPARATORS:
        return [
            artist_name.strip()
            for artist_name in re.split(split_pattern_artists, str(albumartist))
            if artist_name.strip()
        ]

    return [str(albumartist).strip()]


def _extract_valid_mbids(raw: object) -> list[str]:
    if raw is None:
        return []

    text = str(raw)
    return [match.group(0).lower() for match in _MUSICBRAINZ_ID_RE.finditer(text)]


def _resolve_lib(lib=None):
    if lib is None:
        raise ValueError("lib must be passed explicitly")
    return lib


def _needs_alias_lookup(name: str) -> bool:
    return any(ord(c) > 127 for c in name)


def _resolve_canonical_name(artist_name: str) -> str:
    """Resolve a display_name alias to the canonical beets artist name.

    When the URL path uses the EN/FR alias (e.g. "Taeko Onuki") instead of the
    canonical library name (e.g. "大貫妙子"), this maps it back.
    Checks the all-artists Redis cache first, then the user_artist_follow DB.
    Returns artist_name unchanged when no resolution is found.
    """
    # Scan all-artists cache for a matching display_name (fast when cache is warm)
    cached = get_json_cache(_artists_cache_key(None))
    if cached:
        try:
            q = artist_name.casefold()
            for a in json.loads(cached):
                dn = (a.get("display_name") or "").casefold()
                if dn and dn == q:
                    return str(a.get("artist") or artist_name)
        except Exception:
            pass

    # Fallback: check tracked_artist for an original_name match
    try:
        from beets_flask.database.models.users import TrackedArtistInDb
        from beets_flask.database.setup import session_factory

        session = session_factory()
        try:
            row = (
                session.query(TrackedArtistInDb)
                .filter(TrackedArtistInDb.original_name == artist_name)
                .first()
            )
            if row:
                return row.artist_name
        finally:
            session.close()
    except Exception:
        pass

    return artist_name


def _get_artist_mbid_map(lib=None) -> dict[str, str]:
    """Return {normalized_artist_name: mbid} by scanning the items table."""
    beets_lib = _resolve_lib(lib)
    with beets_lib.transaction() as tx:
        rows = tx.query(
            "SELECT artist, mb_artistid FROM items WHERE mb_artistid IS NOT NULL AND mb_artistid != ''"
        )

    result: dict[str, str] = {}
    for artist_str, mbid_str in rows:
        if not artist_str or not mbid_str:
            continue
        if ARTIST_SEPARATORS:
            artist_names = [a.strip() for a in re.split(split_pattern_artists, str(artist_str)) if a.strip()]
        else:
            artist_names = [str(artist_str).strip()]

        mbid_parts = re.split(r"[;,]\s*", str(mbid_str).strip())
        valid_mbids = [m.strip() for m in mbid_parts if _MUSICBRAINZ_ID_RE.fullmatch(m.strip())]

        for i, name in enumerate(artist_names):
            key = _normalize_artist_name(name)
            if key in result:
                continue
            mbid = valid_mbids[i] if i < len(valid_mbids) else (valid_mbids[0] if valid_mbids else None)
            if mbid:
                result[key] = mbid

    return result


def _parse_en_fr_aliases(aliases: list) -> tuple[str | None, list[str]]:
    """Parse MB alias-list → (primary_display_name, all_en_fr_aliases_primary_first).

    Returns the best display name (EN primary > FR primary > EN any > FR any)
    and a deduplicated list of all EN/FR aliases with the primary first — for
    use as search-query fallbacks.
    """
    en_primary: str | None = None
    fr_primary: str | None = None
    en_others: list[str] = []
    fr_others: list[str] = []

    for alias in aliases:
        locale = alias.get("locale")
        if locale not in ("en", "fr"):
            continue
        if alias.get("type") not in ("Artist name", "Legal name", None, ""):
            continue
        candidate = str(alias.get("alias") or alias.get("name") or "").strip()
        if not candidate:
            continue
        is_primary = alias.get("primary") == "primary"
        if locale == "en":
            if is_primary and en_primary is None:
                en_primary = candidate
            elif not is_primary:
                en_others.append(candidate)
        elif locale == "fr":
            if is_primary and fr_primary is None:
                fr_primary = candidate
            elif not is_primary:
                fr_others.append(candidate)

    display_name = en_primary or fr_primary or (en_others[0] if en_others else None) or (fr_others[0] if fr_others else None)

    # Full list: primary aliases first, then all others (deduplicated, preserve order)
    seen: set[str] = set()
    ordered: list[str] = []
    for name in ([en_primary] if en_primary else []) + ([fr_primary] if fr_primary else []) + en_others + fr_others:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)

    return display_name, ordered


def _get_mb_english_alias_cached(mbid: str) -> str | None:
    """Return the primary EN/FR display-name alias for an MBID (Redis-cached 24 h).

    Also populates the mb_aliases_all: cache with the full alias list so that
    _get_mb_all_en_aliases_cached can serve search-fallback names without a
    second MB API call.
    """
    cache_key = f"{MB_ALIAS_CACHE_PREFIX}{mbid}"
    cached = get_json_cache(cache_key)
    if cached is not None:
        try:
            val = json.loads(cached)
            return val if isinstance(val, str) else None
        except (json.JSONDecodeError, ValueError):
            pass

    try:
        _configure_musicbrainz_client()
        musicbrainzngs.set_useragent("beets-flask", "1.0", "https://github.com/pSpitzner/beets-flask")
        result = musicbrainzngs.get_artist_by_id(mbid, includes=["aliases"])
        artist_data = result.get("artist", {})
        aliases = artist_data.get("alias-list", [])

        result_alias, all_aliases = _parse_en_fr_aliases(aliases)

        set_json_cache(cache_key, json.dumps(result_alias), MB_ALIAS_CACHE_TTL_SECONDS)
        set_json_cache(
            f"{MB_ALL_ALIASES_CACHE_PREFIX}{mbid}",
            json.dumps(all_aliases),
            MB_ALIAS_CACHE_TTL_SECONDS,
        )
        return result_alias
    except Exception as exc:
        log.debug("MB alias lookup failed mbid=%s: %s", mbid, exc)
        set_json_cache(cache_key, json.dumps(None), 3600)
        return None


def _get_mb_all_en_aliases_cached(mbid: str) -> list[str]:
    """Return all EN/FR aliases for an MBID, primary first (Redis-cached 24 h).

    Falls back to triggering _get_mb_english_alias_cached when the all-aliases
    cache is cold (the two caches are always populated together).
    """
    all_cache_key = f"{MB_ALL_ALIASES_CACHE_PREFIX}{mbid}"
    cached = get_json_cache(all_cache_key)
    if cached is not None:
        try:
            val = json.loads(cached)
            return val if isinstance(val, list) else []
        except (json.JSONDecodeError, ValueError):
            pass

    # Populate both caches in one MB call then re-read
    _get_mb_english_alias_cached(mbid)
    cached = get_json_cache(all_cache_key)
    if cached:
        try:
            val = json.loads(cached)
            return val if isinstance(val, list) else []
        except Exception:
            pass
    return []


def _get_mb_display_info(artist_name: str, mbid: str | None) -> tuple[str | None, str | None]:
    """Return (display_name, resolved_mbid) for an artist.

    For ASCII-only names returns (None, mbid) immediately.
    For non-ASCII names: uses the known MBID if available, else searches MB by name.
    Both lookups are Redis-cached (24 h).
    """
    if not _needs_alias_lookup(artist_name):
        return (None, mbid)

    # If we already have a MBID, go straight to alias lookup.
    if mbid:
        alias = _get_mb_english_alias_cached(mbid)
        return (alias, mbid)

    # No MBID — check the name-keyed cache first.
    name_cache_key = f"{MB_NAME_CACHE_PREFIX}{_normalize_artist_name(artist_name)}"
    cached = get_json_cache(name_cache_key)
    if cached is not None:
        try:
            val = json.loads(cached)
            if isinstance(val, dict):
                return (val.get("display_name"), val.get("mbid"))
        except (json.JSONDecodeError, ValueError):
            pass

    # Search MB by name to resolve MBID, then fetch alias.
    try:
        _configure_musicbrainz_client()
        musicbrainzngs.set_useragent("beets-flask", "1.0", "https://github.com/pSpitzner/beets-flask")
        mbids = _search_artist_mbid_from_mb(artist_name)
        resolved_mbid = next(iter(sorted(mbids)), None)

        display_name: str | None = None
        if resolved_mbid:
            display_name = _get_mb_english_alias_cached(resolved_mbid)

        set_json_cache(
            name_cache_key,
            json.dumps({"display_name": display_name, "mbid": resolved_mbid}),
            MB_ALIAS_CACHE_TTL_SECONDS,
        )
        return (display_name, resolved_mbid)
    except Exception as exc:
        log.debug("MB name→display lookup failed name=%s: %s", artist_name, exc)
        set_json_cache(name_cache_key, json.dumps({"display_name": None, "mbid": None}), 3600)
        return (None, None)


def _find_artist_mbids(artist_name: str, lib=None) -> set[str]:
    normalized_artist_name = _normalize_artist_name(artist_name)
    mbids: set[str] = set()
    beets_lib = _resolve_lib(lib)

    with beets_lib.transaction() as tx:
        rows = tx.query("SELECT id FROM items WHERE instr(artist, ?) > 0", (artist_name,))

    for row in rows:
        item = beets_lib.get_item(row[0])
        if item is None:
            continue

        artist_names = _artist_names_from_item(item)
        artist_mbids = list(getattr(item, "mb_artistids", []) or [])
        if len(artist_names) != len(artist_mbids):
            continue

        for item_artist_name, mbid in zip(artist_names, artist_mbids, strict=False):
            if _normalize_artist_name(item_artist_name) != normalized_artist_name:
                continue
            for parsed_mbid in _extract_valid_mbids(mbid):
                mbids.add(parsed_mbid)

    return mbids


def _owned_release_group_ids(artist_name: str, lib=None) -> set[str]:
    normalized_artist_name = _normalize_artist_name(artist_name)
    release_group_ids: set[str] = set()
    beets_lib = _resolve_lib(lib)

    with beets_lib.transaction() as tx:
        rows = tx.query(
            "SELECT id FROM albums WHERE instr(albumartist, ?) > 0",
            (artist_name,),
        )

    for row in rows:
        album = beets_lib.get_album(row[0])
        if album is None:
            continue

        if normalized_artist_name not in {
            _normalize_artist_name(name) for name in _albumartist_names_from_album(album)
        }:
            continue

        release_group_id = getattr(album, "mb_releasegroupid", None)

        if release_group_id:
            release_group_ids.add(str(release_group_id))

    return release_group_ids


_MB_RELEASE_TYPE_MAP: dict[str, str] = {
    "Album": "album",
    "EP": "ep",
    "Single": "single",
    "Broadcast": "other",
    "Other": "other",
}

_MB_SECONDARY_TYPE_MAP: dict[str, str] = {
    "Live": "live",
    "Compilation": "compilation",
    "Remix": "remix",
    "Soundtrack": "soundtrack",
}


def _release_type_from_mb(release_group: dict) -> str:
    secondary = release_group.get("secondary-type-list", [])
    for sec_type, mapped in _MB_SECONDARY_TYPE_MAP.items():
        if sec_type in secondary:
            return mapped
    primary = release_group.get("primary-type", "")
    return _MB_RELEASE_TYPE_MAP.get(primary, "album")


def _normalize_for_dedup(title: str) -> str:
    """Normalize an album title for cross-source deduplication.

    Handles Unicode punctuation variants (en-dash, curly apostrophe, …),
    strips common edition/remaster/bonus parenthetical suffixes so that
    "Névrose" and "Névrose (Deluxe Edition)" are treated as the same release.
    """
    # NFKC decomposes compatibility forms (fullwidth chars, ligatures, …)
    t = unicodedata.normalize("NFKC", title).casefold().strip()

    # Normalize all hyphen/dash variants → plain hyphen-minus U+002D
    # Covers: HYPHEN ‐, NON-BREAKING HYPHEN ‑, FIGURE DASH ‒, EN DASH –,
    #         EM DASH —, MINUS SIGN −, SMALL HYPHEN-MINUS ﹣, FULLWIDTH －
    t = re.sub(r"[‐‑‒–—−﹘﹣－]", "-", t)

    # Strip apostrophe/quote variants entirely for dedup robustness:
    # "t'aime" == "taime" regardless of which Unicode apostrophe the source uses.
    # \uXXXX escapes are resolved by Python at parse time → encoding-safe.
    t = re.sub(
        "['`´ʹʻʼʽ''‚‛′‵＇]",
        "",
        t,
    )

    # Normalize conjunction variants → & so "A & B", "A and B", "A et B" all match.
    t = re.sub(r"\s+(?:and|et)\s+", " & ", t)
    t = re.sub(r"\s*&\s*", " & ", t)

    # Remove parenthetical / bracketed edition suffixes
    t = re.sub(
        r"\s*[\(\[][^\)\]]*"
        r"(deluxe|edition|remaster(?:ed)?|re-?master(?:ed)?|bonus"
        r"|explicit|clean|expanded|anniversary|special|standard|extended"
        r"|version|vol\.?|volume)[^\)\]]*[\)\]]",
        "",
        t,
        flags=re.IGNORECASE,
    )

    # Collapse & trim trailing whitespace/punctuation
    return re.sub(r"[\s\-_:]+$", "", t).strip()


def _is_prefix_single_of_owned_title(
    candidate_title_dedup: str,
    owned_titles_dedup: set[str],
) -> bool:
    """Heuristic: Deezer single title is strict prefix of an owned album title.

    Example: single "ten" while owned album "ten days".
    """
    t = candidate_title_dedup.strip()
    if not t or " " in t:
        return False

    for owned in owned_titles_dedup:
        if owned.startswith(f"{t} "):
            return True
    return False


def _owned_album_titles_normalized(artist_name: str, lib=None) -> set[str]:
    normalized_artist_name = _normalize_artist_name(artist_name)
    titles: set[str] = set()
    beets_lib = _resolve_lib(lib)

    with beets_lib.transaction() as tx:
        rows = tx.query(
            "SELECT id FROM albums WHERE instr(albumartist, ?) > 0",
            (artist_name,),
        )

    for row in rows:
        album = beets_lib.get_album(row[0])
        if album is None:
            continue
        if normalized_artist_name not in {
            _normalize_artist_name(name) for name in _albumartist_names_from_album(album)
        }:
            continue
        album_title = getattr(album, "album", None)
        if album_title:

            titles.add(_normalize_for_dedup(str(album_title)))

    return titles


def _search_artist_mbid_from_mb(artist_name: str) -> set[str]:
    """Search MusicBrainz by name and return MBID(s) for the best-matching artist."""
    try:
        result = musicbrainzngs.search_artists(artist=artist_name, limit=5)
        normalized = _normalize_artist_name(artist_name)
        for artist in result.get("artist-list", []):
            if _normalize_artist_name(artist.get("name", "")) == normalized:
                mbids = _extract_valid_mbids(artist.get("id"))
                if mbids:
                    return set(mbids)
        # No exact match — take highest-scored result if score >= 90
        for artist in result.get("artist-list", []):
            score = int(artist.get("ext:score", 0) or 0)
            if score >= 90:
                mbids = _extract_valid_mbids(artist.get("id"))
                if mbids:
                    return set(mbids)
    except Exception:
        pass
    return set()


def _get_tracked_fallback_names(artist_name: str) -> list[str]:
    """Return fallback search names for a tracked-only artist (original_name etc.)."""
    try:
        from beets_flask.database.models.users import TrackedArtistInDb
        from beets_flask.database.setup import session_factory

        session = session_factory()
        try:
            row = (
                session.query(TrackedArtistInDb)
                .filter(TrackedArtistInDb.artist_name == artist_name)
                .first()
            )
            if row and row.original_name and row.original_name != artist_name:
                return [row.original_name]
        finally:
            session.close()
    except Exception:
        pass
    return []


def _safe_int(value) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _release_date_key(date_value: str | None) -> tuple[int, int, int]:
    if not date_value:
        return (9999, 12, 31)

    parts = str(date_value).split("-")
    year = _safe_int(parts[0]) if len(parts) >= 1 else None
    month = _safe_int(parts[1]) if len(parts) >= 2 else None
    day = _safe_int(parts[2]) if len(parts) >= 3 else None
    return (
        year if year is not None else 9999,
        month if month is not None else 12,
        day if day is not None else 31,
    )


_PREFERRED_COUNTRY_ORDER = {
    "XW": 0,  # Worldwide
    "US": 1,
    "GB": 2,
    "FR": 3,
    "DE": 4,
    "CA": 5,
    "JP": 6,
    "BE": 7,
}


def _release_track_count_from_summary(release: dict) -> int | None:
    medium_track_count = _safe_int(release.get("medium-track-count"))
    if medium_track_count is not None:
        return medium_track_count

    total = 0
    found = False
    for medium in release.get("medium-list", []):
        track_count = _safe_int(medium.get("track-count"))
        if track_count is None:
            continue
        total += track_count
        found = True

    if found:
        return total
    return None


def _pick_best_release_for_group(release_group_id: str) -> dict | None:
    rg = musicbrainzngs.get_release_group_by_id(release_group_id, includes=["releases"])
    releases = rg.get("release-group", {}).get("release-list", [])
    if not releases:
        return None

    def sort_key(release: dict) -> tuple:
        status_rank = 0 if str(release.get("status", "")).casefold() == "official" else 1
        country_rank = _PREFERRED_COUNTRY_ORDER.get(str(release.get("country", "")), 99)
        disambiguation_rank = 1 if str(release.get("disambiguation", "")).strip() else 0
        date_rank = _release_date_key(release.get("date"))
        track_count = _release_track_count_from_summary(release)
        has_track_count_rank = 0 if track_count is not None else 1
        track_count_rank = -(track_count or 0)
        return (
            status_rank,
            country_rank,
            disambiguation_rank,
            date_rank,
            has_track_count_rank,
            track_count_rank,
            str(release.get("id", "")),
        )

    return min(releases, key=sort_key)


def _release_track_count_from_detail(release: dict) -> int | None:
    total = 0
    found = False
    for medium in release.get("medium-list", []):
        track_count = _safe_int(medium.get("track-count"))
        if track_count is not None:
            total += track_count
            found = True
            continue

        track_list = medium.get("track-list", [])
        if track_list:
            total += len(track_list)
            found = True

    if found:
        return total
    return None


def _best_release_track_count_for_group(release_group_id: str) -> int | None:
    _configure_musicbrainz_client()
    best_release = _pick_best_release_for_group(release_group_id)
    if best_release is None:
        return None

    track_count = _release_track_count_from_summary(best_release)
    if track_count is not None:
        return track_count

    best_release_id = best_release.get("id")
    if not best_release_id:
        return None

    release = musicbrainzngs.get_release_by_id(best_release_id, includes=["recordings"])
    return _release_track_count_from_detail(release.get("release", {}))


def _best_release_tracks_for_group(release_group_id: str) -> list[dict[str, str | int | None]]:
    _configure_musicbrainz_client()
    best_release = _pick_best_release_for_group(release_group_id)
    if best_release is None:
        return []

    best_release_id = best_release.get("id")
    if not best_release_id:
        return []

    release = musicbrainzngs.get_release_by_id(best_release_id, includes=["recordings"])
    tracks: list[dict[str, str | int | None]] = []
    for medium in release.get("release", {}).get("medium-list", []):
        for track in medium.get("track-list", []):
            recording = track.get("recording", {})
            length_ms = _safe_int(recording.get("length"))
            tracks.append({
                "title": recording.get("title") or track.get("title", ""),
                "duration": length_ms // 1000 if length_ms else None,
                "track_position": _safe_int(track.get("position") or track.get("number")),
            })
    return tracks


def _missing_albums_from_musicbrainz(
    artist_name: str,
    lib=None,
    search_fallback_names: list[str] | None = None,
) -> list[dict[str, str | int | None]]:
    _configure_musicbrainz_client()
    artist_mbids = _find_artist_mbids(artist_name, lib=lib)
    if not artist_mbids:
        # Not in library — union MBIDs from all name variants.
        # Primary name search can return a redirect/alias MBID that differs from the
        # canonical one used in release-group artist credits, so we always also search
        # fallback names (e.g. original MB name for EN-aliased artists) and union the
        # results so the first-credit filter below accepts release groups from either ID.
        artist_mbids = _search_artist_mbid_from_mb(artist_name)
        for fallback in (search_fallback_names or []):
            artist_mbids |= _search_artist_mbid_from_mb(fallback)
    if not artist_mbids:
        return []

    log.info(
        "missing_albums musicbrainz mbids artist=%s count=%s mbids=%s",
        artist_name,
        len(artist_mbids),
        sorted(artist_mbids),
    )

    owned_release_group_ids = _owned_release_group_ids(artist_name, lib=lib)
    owned_titles = _owned_album_titles_normalized(artist_name, lib=lib)
    missing_by_release_group: dict[str, dict[str, str | int | None]] = {}
    had_successful_lookup = False

    for artist_mbid in sorted(artist_mbids):
        try:
            response = musicbrainzngs.browse_release_groups(
                artist=artist_mbid, includes=["artist-credits"]
            )
            had_successful_lookup = True
        except Exception as exc:
            log.warning(
                "missing_albums skip musicbrainz artist id artist=%s mbid=%s error_type=%s error=%s",
                artist_name,
                artist_mbid,
                type(exc).__name__,
                exc,
            )
            continue

        for release_group in response.get("release-group-list", []):
            release_group_id = release_group.get("id")
            if not release_group_id or release_group_id in owned_release_group_ids:
                continue
            # Skip release groups where this artist is only a guest/featured artist.
            # The first entry in artist-credit is the primary credited artist.
            artist_credit = release_group.get("artist-credit") or []
            first_credit = artist_credit[0] if artist_credit else None
            if first_credit:
                first_mbid = (first_credit.get("artist") or {}).get("id")
                if first_mbid and first_mbid not in artist_mbids:
                    continue
            # Also filter by title: catches imported albums whose mb_releasegroupid
            # doesn't match (e.g. beets set a different release ID, or no ID at all)
            title_key = _normalize_for_dedup(release_group.get("title", ""))
            if title_key in owned_titles:
                continue

            missing_by_release_group[release_group_id] = {
                "album": release_group.get("title", ""),
                "year": _extract_release_group_year(
                    release_group.get("first-release-date")
                ),
                "mb_releasegroupid": release_group_id,
                "release_type": _release_type_from_mb(release_group),
                "cover_url": None,
                "track_count": None,
            }

    if not had_successful_lookup:
        fallback_mbids = _search_artist_mbid_from_mb(artist_name)
        extra_mbids = sorted(fallback_mbids - artist_mbids)
        if extra_mbids:
            log.info(
                "missing_albums musicbrainz fallback_mbids artist=%s mbids=%s",
                artist_name,
                extra_mbids,
            )
        for artist_mbid in extra_mbids:
            try:
                response = musicbrainzngs.browse_release_groups(
                    artist=artist_mbid, includes=["artist-credits"]
                )
            except Exception:
                continue

            for release_group in response.get("release-group-list", []):
                release_group_id = release_group.get("id")
                if not release_group_id or release_group_id in owned_release_group_ids:
                    continue
                artist_credit = release_group.get("artist-credit") or []
                first_credit = artist_credit[0] if artist_credit else None
                if first_credit:
                    first_mbid = (first_credit.get("artist") or {}).get("id")
                    if first_mbid and first_mbid not in artist_mbids:
                        continue
                title_key = _normalize_for_dedup(release_group.get("title", ""))
                if title_key in owned_titles:
                    continue

                missing_by_release_group[release_group_id] = {
                    "album": release_group.get("title", ""),
                    "year": _extract_release_group_year(
                        release_group.get("first-release-date")
                    ),
                    "mb_releasegroupid": release_group_id,
                    "release_type": _release_type_from_mb(release_group),
                    "cover_url": None,
                    "track_count": None,
                }

    return list(missing_by_release_group.values())


def _deezer_find_artist_id(artist_name: str, search_names: list[str]) -> int | None:
    """Search Deezer for an artist by trying each name in search_names in order.

    Returns the Deezer artist ID on the first exact name match found, or the top
    result of the last successful search as a last resort.
    """
    norm_names = {_normalize_artist_name(n) for n in [artist_name] + search_names if n}
    last_top: int | None = None

    for query in (search_names or [artist_name]):
        try:
            search_url = (
                "https://api.deezer.com/search/artist?q="
                + urllib.parse.quote(query)
                + "&limit=5"
            )
            with urllib.request.urlopen(search_url, timeout=8) as req:  # noqa: S310
                search_data = json.loads(req.read())
        except Exception:
            continue

        candidates = search_data.get("data", [])
        if not candidates:
            continue

        last_top = candidates[0]["id"]
        for candidate in candidates:
            if _normalize_artist_name(candidate.get("name", "")) in norm_names:
                return candidate["id"]

    return last_top


def _missing_albums_from_deezer(
    artist_name: str,
    owned_titles_dedup: set[str],
    search_names: list[str] | None = None,
) -> dict[str, dict[str, str | int | None]]:
    """Query the Deezer public API for albums not already owned, keyed by dedup title.

    Returns a dict keyed by normalised title so the caller can merge with MusicBrainz
    results. Within Deezer, duplicate editions of the same album (e.g. Deluxe, Explicit)
    are collapsed to the first-seen entry (first-wins keeps the canonical edition that
    Deezer returns first).  The ``mb_releasegroupid`` field is intentionally absent here;
    the caller sets it appropriately depending on whether a matching MB entry exists.

    ``search_names`` is the ordered list of EN/FR aliases to try for the Deezer query
    (primary first); falls back to ``artist_name`` when not provided.
    """
    try:
        artist_id = _deezer_find_artist_id(artist_name, search_names or [artist_name])

        if not artist_id:
            return {}

        albums_url = f"https://api.deezer.com/artist/{artist_id}/albums?limit=200"
        with urllib.request.urlopen(albums_url, timeout=8) as req:  # noqa: S310
            albums_data = json.loads(req.read())

        # Keyed by dedup_key — first-wins deduplication across Deezer editions.
        by_dedup_key: dict[str, dict[str, str | int | None]] = {}
        for album in albums_data.get("data", []):
            title = album.get("title", "")
            dedup_key = _normalize_for_dedup(title)
            if dedup_key in owned_titles_dedup:
                continue

            record_type = str(album.get("record_type", "album"))
            if record_type.casefold() == "single" and _is_prefix_single_of_owned_title(
                dedup_key,
                owned_titles_dedup,
            ):
                continue

            # First-wins: skip later Deezer editions of an already-seen canonical title.
            if dedup_key in by_dedup_key:
                continue

            year_str = str(album.get("release_date", "") or "")
            year: int | None = int(year_str[:4]) if len(year_str) >= 4 else None
            deezer_id = album.get("id")

            # Fetch individual album to verify main artist and get nb_tracks.
            # /artist/{id}/albums also returns albums where the artist is only a
            # contributor (feat.), so we skip those by checking album_detail["artist"]["id"].
            track_count: int | None = None
            if deezer_id:
                try:
                    album_url = f"https://api.deezer.com/album/{deezer_id}"
                    with urllib.request.urlopen(album_url, timeout=5) as req:  # noqa: S310
                        album_detail = json.loads(req.read())
                    main_artist_id = (album_detail.get("artist") or {}).get("id")
                    if main_artist_id and int(main_artist_id) != artist_id:
                        continue
                    track_count = album_detail.get("nb_tracks")
                except Exception:
                    pass

            by_dedup_key[dedup_key] = {
                "album": title,
                "year": year,
                "deezer_id": deezer_id,
                "release_type": record_type,
                "cover_url": album.get("cover_medium") or album.get("cover") or None,
                "track_count": track_count,
            }
        return by_dedup_key

    except Exception:
        return {}


def _missing_albums_from_sources(
    artist_name: str,
    lib=None,
) -> list[dict[str, str | int | None]]:
    """Return missing albums merged from MusicBrainz and Deezer, sorted by year descending.

    Merging strategy:
    - MB albums whose normalised title matches a Deezer album are enriched with
      ``deezer_id`` (and ``cover_url`` / ``track_count`` when MB lacks them).
    - Deezer albums with no MB counterpart become standalone entries carrying
      ``mb_releasegroupid = "deezer:<id>"`` for backward-compat with the download flow.
    - Deezer editions of the same album (Deluxe, Explicit, …) are collapsed to one
      entry before the merge step.
    """
    fallback_names = _get_tracked_fallback_names(artist_name)
    mb_missing = _missing_albums_from_musicbrainz(
        artist_name, lib=lib, search_fallback_names=fallback_names or None
    )
    owned_titles = _owned_album_titles_normalized(artist_name, lib=lib)

    # Build ordered EN/FR search names for Deezer (primary alias first, then fallbacks).
    deezer_search_names: list[str] = []
    if _needs_alias_lookup(artist_name):
        _, resolved_mbid = _get_mb_display_info(artist_name, None)
        if resolved_mbid:
            deezer_search_names = _get_mb_all_en_aliases_cached(resolved_mbid)
        else:
            display_name, _ = _get_mb_display_info(artist_name, None)
            if display_name:
                deezer_search_names = [display_name]

    deezer_by_key = _missing_albums_from_deezer(
        artist_name, owned_titles, search_names=deezer_search_names or None
    )

    # Enrich MB entries with Deezer data when title matches; track which Deezer
    # entries were consumed so we can emit the remainder as standalone rows.
    consumed_deezer_keys: set[str] = set()
    enriched_mb: list[dict[str, str | int | None]] = []
    for m in mb_missing:
        dk = _normalize_for_dedup(str(m["album"]))
        entry = dict(m)
        deezer_match = deezer_by_key.get(dk)
        if deezer_match:
            consumed_deezer_keys.add(dk)
            entry["deezer_id"] = deezer_match["deezer_id"]
            if not entry.get("cover_url"):
                entry["cover_url"] = deezer_match.get("cover_url")
            if not entry.get("track_count"):
                entry["track_count"] = deezer_match.get("track_count")
        enriched_mb.append(entry)

    # Deezer-only entries: keep backward-compat mb_releasegroupid scheme.
    deezer_exclusive: list[dict[str, str | int | None]] = []
    for dk, deezer in deezer_by_key.items():
        if dk in consumed_deezer_keys:
            continue
        deezer_id = deezer.get("deezer_id")
        deezer_exclusive.append({
            "album": deezer["album"],
            "year": deezer.get("year"),
            "mb_releasegroupid": f"deezer:{deezer_id}" if deezer_id else None,
            "release_type": deezer.get("release_type"),
            "cover_url": deezer.get("cover_url"),
            "track_count": deezer.get("track_count"),
        })

    all_missing = enriched_mb + deezer_exclusive

    # Populate track_count for MB-only albums that still have null.
    # Deezer-sourced albums already have nb_tracks; only pure MB entries miss it.
    # Runs once at cache-build time; result is persisted in Redis + SQLite.
    for entry in all_missing:
        if entry.get("track_count") is not None:
            continue
        rgid = entry.get("mb_releasegroupid")
        if not rgid or str(rgid).startswith("deezer:") or str(rgid).startswith("release:"):
            continue
        try:
            count = _best_release_track_count_for_group(str(rgid))
            if count is not None:
                entry["track_count"] = count
        except Exception:
            pass

    return sorted(
        all_missing,
        key=lambda a: (
            a["year"] is None,
            -(a["year"] or 0),
            str(a["album"]).casefold(),
        ),
    )


def recompute_missing_cache_for_artist(artist_name: str, lib=None) -> list[dict[str, str | int | None]]:
    """Compute and persist missing albums for one artist (Redis + DB)."""
    missing = _missing_albums_from_sources(artist_name, lib=lib)
    payload = pd.DataFrame(missing).to_json(orient="records")
    cache_key = _missing_cache_key(artist_name)
    set_json_cache(cache_key, payload, MISSING_CACHE_TTL_SECONDS)
    set_db_missing_cache(artist_name, payload)
    return missing


def _clean_cached_missing_payload(
    artist_name: str,
    payload: str,
    lib=None,
) -> tuple[str, bool]:
    """Drop stale cached missing albums that are now owned in library."""
    try:
        rows = json.loads(payload or "[]")
    except Exception:
        return payload, False

    if not isinstance(rows, list):
        return payload, False

    owned_titles = _owned_album_titles_normalized(artist_name, lib=lib)
    if not owned_titles:
        return payload, False

    cleaned = [
        row
        for row in rows
        if _normalize_for_dedup(str((row or {}).get("album", ""))) not in owned_titles
    ]
    changed = len(cleaned) != len(rows)
    if not changed:
        return payload, False

    cleaned_payload = pd.DataFrame(cleaned).to_json(orient="records")
    return cleaned_payload, True


def _all_library_artist_names(lib=None) -> list[str]:
    """Return deduplicated artist names for full missing-albums cache warmup."""
    artists_albums = get_artists_pandas("albums", lib=lib)
    artists_items = get_artists_pandas("items", lib=lib)
    names = {
        str(name).strip()
        for name in [*artists_albums["artist"].tolist(), *artists_items["artist"].tolist()]
        if str(name).strip()
    }
    return sorted(names, key=lambda n: n.casefold())


def _cached_missing_artist_names() -> set[str]:
    """Return artist names currently present in the persistent missing cache table."""
    try:
        from beets_flask.database.models.states import MissingAlbumCacheInDb
        from beets_flask.database.setup import session_factory

        session = session_factory()
        try:
            rows = session.query(MissingAlbumCacheInDb.artist_name).all()
            return {str(row[0]).strip() for row in rows if row and str(row[0]).strip()}
        finally:
            session.close()
    except Exception as exc:
        log.warning("Could not read missing cache table: %s", exc)
        return set()


def ensure_missing_cache_warmed_for_all_artists(
    *,
    lib=None,
    force_recompute: bool = False,
) -> dict[str, int | bool]:
    """Ensure all library artists have a persistent missing-albums cache entry.

    If ``force_recompute`` is False, only artists missing from the DB cache table are
    computed. If True, every artist is recomputed.
    """
    artist_names = _all_library_artist_names(lib=lib)
    cached_names = _cached_missing_artist_names()

    if force_recompute:
        target_names = artist_names
    else:
        target_names = [name for name in artist_names if name not in cached_names]

    warmed = 0
    failed = 0
    for artist_name in target_names:
        try:
            recompute_missing_cache_for_artist(artist_name, lib=lib)
            warmed += 1
        except Exception as exc:  # pragma: no cover
            failed += 1
            log.warning("Failed warming missing cache for artist=%s: %s", artist_name, exc)

    return {
        "ok": failed == 0,
        "artists_total": len(artist_names),
        "artists_cached_before": len(cached_names & set(artist_names)),
        "artists_warmed": warmed,
        "artists_failed": failed,
    }


def _missing_count_by_artist_name() -> dict[str, int]:
    return get_missing_count_map()


def get_artists_pandas(
    table: str,
    artist: str | None = None,
    include_size: bool = False,
    lib=None,
) -> pd.DataFrame:
    """Get all artists from the database using pandas.

    Returns
    -------
        DataFrame with columns ['artist', 'count', 'last_added', 'first_added', ('total_size' if include_size)]
    """
    if table == "items":
        if include_size:
            # Beets has no 'size' column; estimate bytes from length (seconds) * bitrate (bps) / 8
            query = """
                SELECT
                    artist,
                    added,
                    CAST(length * bitrate / 8 AS INTEGER) AS estimated_size
                FROM
                    items
            """
        else:
            query = """
                SELECT
                    artist,
                    added
                FROM
                    items
            """
    elif table == "albums":
        query = """
            SELECT
                albumartist AS artist,
                added

            FROM
                albums
        """
    else:
        raise ValueError(f"Invalid table name: {table}. Must be 'items' or 'albums'.")

    # Split the artist string by the specified separators
    artists: list[str] | None
    if len(ARTIST_SEPARATORS) > 0 and artist is not None:
        artists = [a.strip() for a in re.split(split_pattern_artists, artist)]
    elif artist is not None:
        artists = [artist.strip()]
    else:
        artists = None

    if artists is not None:
        # If an artist is specified, filter the query
        for i, a in enumerate(artists):
            if i == 0:
                query += f" WHERE instr(artist, ?) > 0"
            else:
                query += f" AND instr(artist, ?) > 0"

    beets_lib = _resolve_lib(lib)
    with beets_lib.transaction() as tx:
        rows = tx.query(query, artists) if artists else tx.query(query)

    # Read from the database
    if include_size and table == "items":
        df = pd.DataFrame(rows, columns=["artist", "added", "estimated_size"])
    else:
        df = pd.DataFrame(rows, columns=["artist", "added"])

    # Split artist strings into lists and explode into separate rows
    if len(ARTIST_SEPARATORS) > 0:
        df["artist"] = df["artist"].str.split(split_pattern_artists)
        df = df.explode("artist")

    # Strip whitespace
    df["artist"] = df["artist"].str.strip()
    df["added"] = df["added"] * 1000

    # Group by artist and aggregate
    if include_size and table == "items":
        result = (
            df.groupby("artist")
            .agg(
                count=("artist", "size"),
                last_added=("added", "max"),
                first_added=("added", "min"),
                total_size=("estimated_size", "sum"),
            )
            .reset_index()
        )
    else:
        result = (
            df.groupby("artist")
            .agg(
                count=("artist", "size"),
                last_added=("added", "max"),
                first_added=("added", "min"),
            )
            .reset_index()
        )

    if artists is not None:
        # If an artist is specified, filter the result (respect the separator and resolve as or)
        result = result[
            result["artist"].str.contains(
                _split_pattern(artists), case=False, regex=True
            )
        ]
        # Overwrite if there are multiple artists (i.e. joined by a separator)
        if len(artists) > 1 and not result.empty:
            result["artist"] = artist

    return result

router = APIRouter(tags=["library"])


# NOTE: specific routes (with literal path suffixes) registered BEFORE
# the wildcard {artist_name:path} routes to avoid greedy matching.


@router.post("/artists/missing/cache/warm-all")
async def warm_all_missing_albums_cache(lib: BeetsLib, force: bool = False) -> dict:
    result = ensure_missing_cache_warmed_for_all_artists(lib=lib, force_recompute=force)
    return result


@router.post("/artists/cache/refresh")
async def refresh_artists_cache() -> dict:
    cleared = invalidate_artists_cache()
    return {"ok": True, "cleared": cleared}


@router.post("/artists/mb-alias-cache/refresh")
async def refresh_mb_alias_cache() -> dict:
    """Purge all cached MusicBrainz alias lookups (forces re-fetch on next request)."""
    cleared_alias = invalidate_prefix(MB_ALIAS_CACHE_PREFIX)
    cleared_name = invalidate_prefix(MB_NAME_CACHE_PREFIX)
    # Also bust the artists list cache so display_names are recomputed immediately.
    invalidate_artists_list_cache()
    return {"ok": True, "cleared_alias": cleared_alias, "cleared_name": cleared_name}


@router.get("/missing-album-tracks")
async def missing_album_tracks(id: str = "") -> list:
    if not id:
        raise HTTPException(status_code=400, detail="id is required")

    if id.startswith("deezer:"):
        deezer_id = id[7:]
        try:
            with urllib.request.urlopen(  # noqa: S310
                f"https://api.deezer.com/album/{deezer_id}/tracks", timeout=8
            ) as req:
                data = json.loads(req.read())
            return [
                {
                    "title": t.get("title", ""),
                    "duration": t.get("duration"),
                    "track_position": t.get("track_position"),
                }
                for t in data.get("data", [])
            ]
        except Exception:
            return []
    else:
        try:
            return _best_release_tracks_for_group(id)
        except Exception:
            return []


@router.get("/artists/{artist_name:path}/missing")
async def missing_albums_by_artist(artist_name: str, lib: BeetsLib, refresh: bool = False) -> Response:
    artist_name = _resolve_canonical_name(artist_name)
    cache_key = _missing_cache_key(artist_name)
    log.info("missing_albums request artist=%s refresh=%s", artist_name, refresh)

    if not refresh:
        cached = get_json_cache(cache_key)
        if cached is not None:
            cached, changed = _clean_cached_missing_payload(artist_name, cached, lib=lib)
            if changed:
                set_json_cache(cache_key, cached, MISSING_CACHE_TTL_SECONDS)
            set_db_missing_cache(artist_name, cached)
            log.info("missing_albums redis_hit artist=%s", artist_name)
            return Response(content=cached, media_type="application/json")

        log.info("missing_albums redis_miss artist=%s", artist_name)
        db_cached = get_db_missing_cache(artist_name)
        if db_cached is not None:
            db_cached, changed = _clean_cached_missing_payload(artist_name, db_cached, lib=lib)
            log.info("missing_albums db_hit artist=%s", artist_name)
            set_json_cache(cache_key, db_cached, MISSING_CACHE_TTL_SECONDS)
            if changed:
                set_db_missing_cache(artist_name, db_cached)
            return Response(content=db_cached, media_type="application/json")
        log.info("missing_albums db_miss artist=%s", artist_name)
    else:
        log.info("missing_albums force_refresh artist=%s", artist_name)

    invalidate_artists_list_cache()
    try:
        missing = recompute_missing_cache_for_artist(artist_name, lib=lib)
    except musicbrainzngs.musicbrainz.MusicBrainzError as exc:
        log.warning("missing_albums musicbrainz_error artist=%s error=%s", artist_name, exc)
        return Response(content="[]", media_type="application/json")

    payload = pd.DataFrame(missing).to_json(orient="records")
    log.info("missing_albums computed artist=%s count=%s", artist_name, len(missing))
    return Response(content=payload, media_type="application/json")


@router.get("/artists/{artist_name:path}")
async def artist_by_name(artist_name: str, lib: BeetsLib, user: CurrentUser) -> Response:
    return await _get_artists(artist_name, lib, user.id)


@router.get("/artists")
async def all_artists(lib: BeetsLib, user: CurrentUser) -> Response:
    return await _get_artists(None, lib, user.id)


async def _get_artists(artist_name: str | None, lib, user_id: str) -> Response:
    import unicodedata

    from beets_flask.library_cache import get_missing_count_map

    # Trailing slash in URL causes {artist_name:path} to capture "" — treat as None (all artists).
    if not artist_name:
        artist_name = None

    # Resolve EN/FR display_name alias → canonical beets name (e.g. "Taeko Onuki" → "大貫妙子")
    if artist_name is not None:
        artist_name = _resolve_canonical_name(artist_name)

    cache_key = _artists_cache_key(artist_name)
    cached = get_json_cache(cache_key)
    if cached is not None:
        return Response(content=cached, media_type="application/json")

    artists_albums = (
        get_artists_pandas("albums", artist_name, lib=lib)
        .rename(columns={"count": "album_count", "last_added": "last_album_added", "first_added": "first_album_added"})
        .set_index("artist")
    )
    artists_items = (
        get_artists_pandas("items", artist_name, include_size=True, lib=lib)
        .rename(columns={"count": "item_count", "last_added": "last_item_added", "first_added": "first_item_added"})
        .set_index("artist")
    )

    artists = artists_albums.join(artists_items, how="outer").reset_index()
    artists["album_count"] = artists["album_count"].fillna(0).astype(int)
    artists["item_count"] = artists["item_count"].fillna(0).astype(int)
    artists["total_size"] = artists["total_size"].fillna(0).astype(int)

    # ── MusicBrainz enrichment: MBID dedup + EN/FR display-name alias ──────────
    if not artists.empty:
        if artist_name is not None:
            # Single artist: per-artist MBID lookup then display info
            mbids = _find_artist_mbids(artist_name, lib=lib)
            mbid = next(iter(sorted(mbids)), None)
            display_name, resolved_mbid = _get_mb_display_info(artist_name, mbid)
            final_mbid = resolved_mbid or mbid
            artists["mb_artist_id"] = final_mbid
            artists["display_name"] = display_name
            artists["mb_url"] = f"https://musicbrainz.org/artist/{final_mbid}" if final_mbid else None
        else:
            # All artists: full MBID map + merge duplicate names sharing same MBID
            mbid_map = _get_artist_mbid_map(lib=lib)
            artists["mb_artist_id"] = artists["artist"].apply(
                lambda n: mbid_map.get(_normalize_artist_name(str(n)))
            )

            has_mbid = artists["mb_artist_id"].notna()
            if has_mbid.any():
                with_mbid = artists[has_mbid].copy()
                without_mbid = artists[~has_mbid].copy()

                # Canonical name = variant with the most albums per MBID
                canonical_idx = with_mbid.groupby("mb_artist_id")["album_count"].idxmax()
                canonical_names = (
                    with_mbid.loc[canonical_idx, ["mb_artist_id", "artist"]]
                    .set_index("mb_artist_id")["artist"]
                )

                sum_cols = [c for c in ["album_count", "item_count", "total_size"] if c in with_mbid.columns]
                max_cols = [c for c in ["last_album_added", "last_item_added"] if c in with_mbid.columns]
                min_cols = [c for c in ["first_album_added", "first_item_added"] if c in with_mbid.columns]

                agg_kwargs: dict = {c: (c, "sum") for c in sum_cols}
                agg_kwargs.update({c: (c, "max") for c in max_cols})
                agg_kwargs.update({c: (c, "min") for c in min_cols})

                agg = with_mbid.groupby("mb_artist_id").agg(**agg_kwargs).reset_index()
                agg["artist"] = agg["mb_artist_id"].map(canonical_names)
                artists = pd.concat([agg, without_mbid], ignore_index=True)

            # EN/FR alias — falls back to MB name search when no local MBID
            def _mb_enrich(row) -> "pd.Series[object]":
                name = str(row["artist"])
                existing_mbid = row["mb_artist_id"] if pd.notna(row["mb_artist_id"]) else None
                dn, resolved = _get_mb_display_info(name, existing_mbid)
                final = resolved or existing_mbid
                return pd.Series({
                    "display_name": dn,
                    "mb_artist_id": final,
                    "mb_url": f"https://musicbrainz.org/artist/{final}" if final else None,
                })

            enriched = artists.apply(_mb_enrich, axis=1)
            artists["display_name"] = enriched["display_name"]
            artists["mb_artist_id"] = enriched["mb_artist_id"]
            artists["mb_url"] = enriched["mb_url"]
    # ─────────────────────────────────────────────────────────────────────────

    missing_count_map = get_missing_count_map()
    artists["missing_count"] = (
        artists["artist"]
        .apply(lambda n: missing_count_map.get(unicodedata.normalize("NFC", str(n)).strip(), 0))
        .fillna(0)
        .astype(int)
    )

    if artist_name is not None:
        if artists.empty:
            from beets_flask.discovery.tracked_artists import get_tracked_artist

            tracked = get_tracked_artist(artist_name)
            if tracked is None:
                # Also try resolving by original_name (artist_name may be the alias used in the URL)
                from beets_flask.discovery.tracked_artists import get_tracked_artists
                all_tracked = {a["name"].lower(): a for a in get_tracked_artists()}
                tracked = all_tracked.get(artist_name.lower())
            if tracked:
                stub = {
                    "artist": tracked["name"],
                    "display_name": None,
                    "album_count": 0,
                    "item_count": 0,
                    "total_size": 0,
                    "missing_count": 0,
                    "in_library": False,
                }
                return Response(content=json.dumps(stub), media_type="application/json")
            raise NotFoundException(f"Artist '{artist_name}' not found.")

        payload = artists.iloc[0].to_json()
        set_json_cache(cache_key, payload, ARTISTS_CACHE_TTL_SECONDS)
        return Response(content=payload, media_type="application/json")

    payload = artists.to_json(orient="records")
    set_json_cache(cache_key, payload, ARTISTS_CACHE_TTL_SECONDS)
    return Response(content=payload, media_type="application/json")
