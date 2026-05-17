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

/* ──────────────────── Download stubs (Phase 3) ─────────────────── */

export type DownloadStatus = 'pending' | 'downloading' | 'done' | 'error';

export interface DownloadJob {
    job_id: string;
    deezer_id: string;
    album: string;
    artist: string;
    status: DownloadStatus;
    error?: string | null;
    created_at: string;
    completed_at?: string | null;
    output_path?: string | null;
}
