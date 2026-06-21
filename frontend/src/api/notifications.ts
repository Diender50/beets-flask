import { queryOptions } from '@tanstack/react-query';

export interface AlbumNotification {
    id: string;
    artist_name: string;
    album_key: string;
    album: {
        album?: string;
        year?: number | null;
        cover_url?: string | null;
        release_type?: string | null;
        mb_releasegroupid?: string | null;
        deezer_id?: number | null;
        track_count?: number | null;
    };
    seen: boolean;
    seen_at: string | null;
    created_at: string | null;
}

export interface NotificationCount {
    unseen: number;
}

export const notificationCountQueryOptions = () =>
    queryOptions({
        queryKey: ['notifications', 'count'],
        queryFn: async (): Promise<NotificationCount> => {
            const res = await fetch('/notifications/count');
            if (!res.ok) return { unseen: 0 };
            return res.json();
        },
        refetchInterval: 5 * 60 * 1000, // re-poll every 5 min
        staleTime: 60 * 1000,
    });

export const notificationsQueryOptions = (unseenOnly = false) =>
    queryOptions({
        queryKey: ['notifications', 'list', { unseenOnly }],
        queryFn: async (): Promise<AlbumNotification[]> => {
            const url = unseenOnly
                ? '/notifications?unseen_only=true'
                : '/notifications';
            const res = await fetch(url);
            if (!res.ok) return [];
            return res.json();
        },
    });

export const followedArtistsQueryOptions = () =>
    queryOptions({
        queryKey: ['notifications', 'followed'],
        queryFn: async (): Promise<string[]> => {
            const res = await fetch('/discovery/artists/followed');
            if (!res.ok) return [];
            return res.json();
        },
    });

export async function followArtist(name: string): Promise<void> {
    const res = await fetch(`/discovery/artists/${encodeURIComponent(name)}/follow`, {
        method: 'POST',
    });
    if (!res.ok) throw new Error('Failed to follow artist');
}

export async function unfollowArtist(name: string): Promise<void> {
    const res = await fetch(`/discovery/artists/${encodeURIComponent(name)}/unfollow`, {
        method: 'POST',
    });
    if (!res.ok) throw new Error('Failed to unfollow artist');
}

export async function markNotificationsSeen(ids?: string[]): Promise<{ updated: number }> {
    const res = await fetch('/notifications/seen', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(ids ? { ids } : {}),
    });
    if (!res.ok) throw new Error('Failed to mark notifications seen');
    return res.json();
}
