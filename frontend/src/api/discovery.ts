import { queryOptions } from '@tanstack/react-query';

/* ─────────────────────── Followed Artists ──────────────────────── */

export interface FollowedArtist {
    name: string;
    added_at: string;
}

export const followedArtistsQueryOptions = () =>
    queryOptions({
        queryKey: ['followedArtists'],
        queryFn: async (): Promise<FollowedArtist[]> => {
            const response = await fetch('/discovery/artists');
            if (!response.ok) return [];
            return response.json();
        },
    });

export async function followArtist(name: string): Promise<FollowedArtist> {
    const response = await fetch('/discovery/artists', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
    });
    if (!response.ok) {
        const text = await response.text();
        throw new Error(text || 'Follow request failed');
    }
    return response.json();
}

export async function unfollowArtist(name: string): Promise<void> {
    await fetch(`/discovery/artists/${encodeURIComponent(name)}`, {
        method: 'DELETE',
    });
}

/* ───────────────────── Deezer Artist Search ────────────────────── */

export interface ArtistSearchResult {
    id: string;
    name: string;
    sort_name?: string;
    disambiguation?: string;
    country?: string;
    score?: number;
    followed: boolean;
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
    provider: 'deemix' | 'slskd' | 'squidwtf';
    quality: DownloadQuality;
    albums: Array<{
        album: string;
        artist: string;
        release_id?: string;
        deezer_id?: string;
        squid_album_id?: string;
    }>;
}): Promise<{
    provider: string;
    quality: DownloadQuality;
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
