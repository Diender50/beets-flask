import { queryOptions } from '@tanstack/react-query';

const TOKEN_KEY = 'beets_flask_token';

// ── Token storage ─────────────────────────────────────────────────────────────

export function getToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
    localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
    localStorage.removeItem(TOKEN_KEY);
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface UserProfile {
    id: string;
    username: string;
    is_admin: boolean;
    is_active: boolean;
    can_auto_download: boolean;
    can_manual_download: boolean;
    can_retag: boolean;
    can_delete: boolean;
    can_add_artist: boolean;
    max_quality: 'flac' | 'high_lossy' | 'med_lossy' | 'low_lossy';
}

export interface UserInList extends UserProfile {}

export interface LoginResponse {
    token: string;
    user: UserProfile;
}

// ── API calls ─────────────────────────────────────────────────────────────────

export async function login(
    username: string,
    password: string
): Promise<LoginResponse> {
    const res = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
        const text = await res.text().catch(() => 'Login failed');
        throw new Error(text);
    }
    return res.json() as Promise<LoginResponse>;
}

export async function register(
    username: string,
    password: string
): Promise<LoginResponse> {
    const res = await fetch('/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
        const text = await res.text().catch(() => 'Registration failed');
        throw new Error(text);
    }
    return res.json() as Promise<LoginResponse>;
}

export async function getMe(): Promise<UserProfile> {
    const res = await fetch('/auth/me');
    if (!res.ok) throw new Error('Failed to load user');
    return res.json() as Promise<UserProfile>;
}

export async function changePassword(
    oldPassword: string,
    newPassword: string
): Promise<void> {
    const res = await fetch('/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            old_password: oldPassword,
            new_password: newPassword,
        }),
    });
    if (!res.ok) {
        const text = await res.text().catch(() => 'Failed to change password');
        throw new Error(text);
    }
}

// ── Admin user management ─────────────────────────────────────────────────────

export async function listUsers(): Promise<UserInList[]> {
    const res = await fetch('/users');
    if (!res.ok) throw new Error('Failed to load users');
    return res.json() as Promise<UserInList[]>;
}

export interface CreateUserPayload {
    username: string;
    password: string;
    is_admin?: boolean;
    can_auto_download?: boolean;
    can_manual_download?: boolean;
    can_retag?: boolean;
    can_delete?: boolean;
    can_add_artist?: boolean;
    max_quality?: UserProfile['max_quality'];
}

export async function createUser(
    payload: CreateUserPayload
): Promise<UserInList> {
    const res = await fetch('/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        const text = await res.text().catch(() => 'Failed to create user');
        throw new Error(text);
    }
    return res.json() as Promise<UserInList>;
}

export interface UpdateUserPayload {
    is_active?: boolean;
    is_admin?: boolean;
    can_auto_download?: boolean;
    can_manual_download?: boolean;
    can_retag?: boolean;
    can_delete?: boolean;
    can_add_artist?: boolean;
    max_quality?: UserProfile['max_quality'];
    password?: string;
}

export async function updateUser(
    userId: string,
    payload: UpdateUserPayload
): Promise<UserInList> {
    const res = await fetch(`/users/${userId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        const text = await res.text().catch(() => 'Failed to update user');
        throw new Error(text);
    }
    return res.json() as Promise<UserInList>;
}

export async function deleteUser(userId: string): Promise<void> {
    const res = await fetch(`/users/${userId}`, { method: 'DELETE' });
    if (!res.ok) {
        const text = await res.text().catch(() => 'Failed to delete user');
        throw new Error(text);
    }
}

// ── Follows ───────────────────────────────────────────────────────────────────

export interface ArtistFollow {
    artist_name: string;
    is_following: boolean;
    added_at: string;
}

export async function getMyFollows(): Promise<ArtistFollow[]> {
    const res = await fetch('/users/me/follows');
    if (!res.ok) throw new Error('Failed to load follows');
    return res.json() as Promise<ArtistFollow[]>;
}

export async function setFollow(
    artistName: string,
    following: boolean
): Promise<ArtistFollow> {
    const res = await fetch(
        `/users/me/follows/${encodeURIComponent(artistName)}`,
        {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ following }),
        }
    );
    if (!res.ok) {
        const text = await res.text().catch(() => 'Failed to update follow');
        throw new Error(text);
    }
    return res.json() as Promise<ArtistFollow>;
}

// ── React Query options ───────────────────────────────────────────────────────

export async function checkNeedsSetup(): Promise<{ needs_setup: boolean }> {
    try {
        const res = await fetch('/auth/needs-setup');
        if (!res.ok) return { needs_setup: false };
        return res.json() as Promise<{ needs_setup: boolean }>;
    } catch {
        return { needs_setup: false };
    }
}

export const needsSetupQueryOptions = () =>
    queryOptions({
        queryKey: ['auth', 'needs-setup'],
        queryFn: checkNeedsSetup,
        staleTime: 30 * 1000,
        retry: false,
    });

export const meQueryOptions = () =>
    queryOptions({
        queryKey: ['me'],
        queryFn: getMe,
        staleTime: 5 * 60 * 1000, // 5 min
        retry: false,
    });

export const usersQueryOptions = () =>
    queryOptions({
        queryKey: ['users'],
        queryFn: listUsers,
    });

export const myFollowsQueryOptions = () =>
    queryOptions({
        queryKey: ['follows', 'me'],
        queryFn: getMyFollows,
    });
