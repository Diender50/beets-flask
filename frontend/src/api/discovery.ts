import { queryOptions } from '@tanstack/react-query';

/* ─────────────────────── Quality Priority ──────────────────────── */

export const qualityPriorityQueryOptions = () =>
    queryOptions({
        queryKey: ['qualityPriority'],
        queryFn: async (): Promise<string[]> => {
            const response = await fetch('/discovery/quality-priority');
            if (!response.ok) return [];
            const data = await response.json();
            return Array.isArray(data.quality_priority) ? data.quality_priority : [];
        },
        staleTime: Infinity,
    });

/* ─────────────────────── Tracked Artists ───────────────────────── */

export interface TrackedArtist {
    name: string;
    added_at: string;
    missing_count?: number;
    /** Original MusicBrainz name when it differs from the EN/FR alias stored in `name`. */
    original_name?: string | null;
}

export const trackedArtistsQueryOptions = () =>
    queryOptions({
        queryKey: ['trackedArtists'],
        queryFn: async (): Promise<TrackedArtist[]> => {
            const response = await fetch('/discovery/artists');
            if (!response.ok) return [];
            return response.json();
        },
    });

export async function addTrackedArtist(name: string, original_name?: string | null): Promise<TrackedArtist> {
    const response = await fetch('/discovery/artists', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, ...(original_name ? { original_name } : {}) }),
    });
    if (!response.ok) {
        const text = await response.text();
        throw new Error(text || 'Add artist request failed');
    }
    return response.json();
}

export async function removeTrackedArtist(name: string): Promise<{ ok: boolean; albums_deleted: number }> {
    const response = await fetch(`/discovery/artists/${encodeURIComponent(name)}`, {
        method: 'DELETE',
    });
    if (!response.ok) {
        const text = await response.text().catch(() => response.statusText);
        throw new Error(`Remove artist failed (${response.status}): ${text}`);
    }
    return response.json();
}

/* ──────────────────── Artist Search (MB + Deezer) ──────────────── */

export interface ArtistSearchResult {
    /** MusicBrainz UUID, or null for Deezer-only results. */
    id: string | null;
    /** Primary display name: EN/FR primary alias when available, otherwise original MB name. */
    name: string;
    /** Original MusicBrainz name when it differs from `name`. Download search fallback only. */
    original_name?: string | null;
    sort_name?: string | null;
    disambiguation?: string | null;
    country?: string | null;
    score?: number;
    tracked: boolean;
    mb_url?: string | null;
    deezer_id?: number | null;
}

export async function searchArtists(q: string): Promise<ArtistSearchResult[]> {
    const response = await fetch(
        `/discovery/search/artists?q=${encodeURIComponent(q)}`
    );
    if (!response.ok) {
        const text = await response.text().catch(() => response.statusText);
        throw new Error(`Search failed (${response.status}): ${text}`);
    }
    return response.json();
}

/* ──────────────────── Download (Phase 3) ───────────────────────── */

export type DownloadStatus = 'pending' | 'downloading' | 'done' | 'error';
export type DownloadQuality = 'flac' | '320' | '128';

export interface DownloadJob {
    job_id: string;
    provider?: 'auto' | 'deemix' | 'slskd' | 'squidwtf';
    deezer_id: string;
    squid_album_id?: string | null;
    album: string;
    artist: string;
    status: DownloadStatus;
    error?: string | null;
    created_at: string;
    completed_at?: string | null;
    output_path?: string | null;
    query?: string | null;
    release_id?: string | null;
    selected_match?: Record<string, unknown> | null;
    provider_candidates?: Array<Record<string, unknown>> | null;
    selection_reason?: string | null;
    stage?: string | null;
    progress_message?: string | null;
}

export interface DownloadSuggestion {
    provider: 'deemix' | 'slskd' | 'squidwtf';
    score: number;
    title: string;
    artist: string;
    details: Record<string, unknown>;
}

export interface DownloadSuggestionsResponse {
    artist: string;
    album: string;
    results: DownloadSuggestion[];
}

export async function getDownloadSuggestions(opts: {
    album: string;
    artist: string;
    provider?: 'deemix' | 'slskd' | 'squidwtf';
    expected_track_count?: number | null;
    expected_tracks?: Array<{ title: string; duration?: number }>;
    /** Phase 2 for slskd: search with original_name only (primary already returned). */
    extended?: boolean;
    signal?: AbortSignal;
}): Promise<DownloadSuggestionsResponse> {
    const controller = new AbortController();
    let timedOut = false;
    const timeout = setTimeout(() => {
        timedOut = true;
        controller.abort();
    }, 120_000);
    const relayAbort = () => controller.abort();
    opts.signal?.addEventListener('abort', relayAbort, { once: true });
    let response: Response;
    try {
        response = await fetch('/discovery/download/options', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                album: opts.album,
                artist: opts.artist,
                provider: opts.provider,
                ...(opts.expected_track_count != null ? { expected_track_count: opts.expected_track_count } : {}),
                ...(opts.expected_tracks?.length ? { expected_tracks: opts.expected_tracks } : {}),
                ...(opts.extended ? { extended: true } : {}),
            }),
            signal: controller.signal,
        });
    } catch (error) {
        if (timedOut && error instanceof DOMException && error.name === 'AbortError') {
            throw new Error('Load download suggestions timed out after 120s');
        }
        throw error;
    } finally {
        clearTimeout(timeout);
        opts.signal?.removeEventListener('abort', relayAbort);
    }

    if (!response.ok) {
        const text = await response.text().catch(() => response.statusText);
        throw new Error(`Load download suggestions failed (${response.status}): ${text}`);
    }
    return response.json();
}

export async function startDownload(opts: {
    album: string;
    artist: string;
    provider?: 'deemix' | 'slskd' | 'squidwtf';
    quality?: DownloadQuality;
    deezer_id?: string;
    squid_album_id?: string;
    squid_quality?: string;
    candidate?: Record<string, unknown>;
    release_id?: string;
}): Promise<DownloadJob> {
    const response = await fetch('/discovery/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(opts),
    });
    if (!response.ok) {
        const text = await response.text().catch(() => response.statusText);
        throw new Error(`Download failed (${response.status}): ${text}`);
    }
    return response.json();
}

export async function startBatchDownload(opts: {
    providers: Array<'deemix' | 'slskd' | 'squidwtf'>;
    qualities: DownloadQuality[];
    albums: Array<{
        album: string;
        artist: string;
        release_id?: string;
        deezer_id?: string;
        squid_album_id?: string;
    }>;
}): Promise<{
    providers: string[];
    qualities: DownloadQuality[];
    requested: number;
    queued: number;
    failed: number;
    jobs: DownloadJob[];
    errors: Array<{ index: number; artist: string; album: string; error: string; status: number }>;
}> {
    const response = await fetch('/discovery/download/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(opts),
    });

    const payload = await response.json();
    if (!response.ok) {
        const message = typeof payload?.error === 'string' ? payload.error : 'Batch download failed';
        throw new Error(message);
    }
    return payload;
}

export async function getDownloadJob(jobId: string): Promise<DownloadJob> {
    const response = await fetch(`/discovery/download/${encodeURIComponent(jobId)}`);
    if (!response.ok) {
        const text = await response.text().catch(() => response.statusText);
        throw new Error(`Load download job failed (${response.status}): ${text}`);
    }
    return response.json();
}

export interface BestRejected {
    provider: string;
    score: number;
    title: string;
    quality: string;
    details: Record<string, unknown>;
}

export interface ProbeAndQueueResult {
    status: 'queued' | 'not_found' | 'error';
    provider?: string;
    score?: number;
    result_title?: string;
    quality?: string;
    job_id?: string;
    error?: string;
    artist?: string;
    album?: string;
    best_rejected?: BestRejected;
}

export async function probeAndQueueDownload(opts: {
    album: string;
    artist: string;
    providers?: Array<'deemix' | 'slskd' | 'squidwtf'>;
    qualities?: string[];
    release_id?: string;
    deezer_id?: string;
    squid_album_id?: string;
    expected_tracks?: Array<{ title: string; duration?: number }>;
    signal?: AbortSignal;
}): Promise<ProbeAndQueueResult> {
    const { signal, ...body } = opts;
    const response = await fetch('/discovery/download/probe-and-queue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal,
    });
    if (!response.ok) {
        const text = await response.text().catch(() => response.statusText);
        throw new Error(`Probe and queue failed (${response.status}): ${text}`);
    }
    return response.json();
}

export async function cleanupSlskdSearches(opts: {
    album: string;
    artist: string;
    searchIds?: string[];
}): Promise<number> {
    const response = await fetch('/discovery/download/slskd/searches', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            album: opts.album,
            artist: opts.artist,
            search_ids: opts.searchIds ?? [],
        }),
    });
    if (!response.ok) {
        return 0;
    }
    const payload = (await response.json()) as { deleted?: unknown };
    const deleted = Number(payload.deleted);
    return Number.isFinite(deleted) && deleted > 0 ? deleted : 0;
}
