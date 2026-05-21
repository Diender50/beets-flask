import {
    AudioLinesIcon,
    ChevronRight,
    ClockIcon,
    Disc3Icon,
    User2Icon,
} from 'lucide-react';
import { useMemo } from 'react';
import {
    Box,
    Button,
    Typography,
    useTheme,
} from '@mui/material';
import { useSuspenseQuery } from '@tanstack/react-query';
import { createFileRoute, Link } from '@tanstack/react-router';

import { inboxStatsQueryOptions } from '@/api/inbox';
import {
    Artist,
    artistsQueryOptions,
    libraryStatsQueryOptions,
    recentAlbumsQueryOptions,
} from '@/api/library';
import { PageWrapper } from '@/components/common/page';
import { relativeTime } from '@/components/common/units/time';
import { InboxStatsCard, LibraryStatsCard } from '@/components/frontpage/statsCard';
import { CoverArt } from '@/components/library/coverArt';
import { AlbumResponseMinimal } from '@/pythonTypes';

export const Route = createFileRoute('/library/browse/')({
    component: RouteComponent,
    loader: async (opts) => {
        await Promise.all([
            opts.context.queryClient.ensureQueryData(artistsQueryOptions()),
            opts.context.queryClient.ensureQueryData(recentAlbumsQueryOptions),
            opts.context.queryClient.ensureQueryData(libraryStatsQueryOptions()),
            opts.context.queryClient.ensureQueryData(inboxStatsQueryOptions()),
        ]);
    },
});

function RouteComponent() {
    const { data: libraryStats } = useSuspenseQuery(libraryStatsQueryOptions());
    const { data: inboxStats } = useSuspenseQuery(inboxStatsQueryOptions());

    return (
        <PageWrapper
            sx={(theme) => ({
                display: 'flex',
                flexDirection: 'column',
                gap: 3,
                py: 2,
                px: 2,
                overflow: 'auto',
                [theme.breakpoints.up('laptop')]: {
                    px: 3,
                    py: 3,
                },
            })}
        >
            {/* Compact stats strip */}
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}>
                <LibraryStatsCard libraryStats={libraryStats} />
                {inboxStats.map((inbox, i) => (
                    <InboxStatsCard inboxStats={inbox} key={i} />
                ))}
            </Box>

            {/* Main content: Albums + Artists */}
            <Box
                sx={(theme) => ({
                    display: 'grid',
                    gap: 3,
                    gridTemplateColumns: '1fr',
                    [theme.breakpoints.up('laptop')]: {
                        gridTemplateColumns: '1fr 1fr',
                        alignItems: 'start',
                    },
                })}
            >
                <RecentAlbums />
                <ArtistsSection />
            </Box>
        </PageWrapper>
    );
}

/* ─────────────────────────── Recent Albums ─────────────────────────── */

function RecentAlbums() {
    const { data: albums } = useSuspenseQuery(recentAlbumsQueryOptions);

    return (
        <Box>
            <SectionHeader
                icon={<Disc3Icon size={16} />}
                title="Recent Albums"
                action={
                    <Button
                        size="small"
                        endIcon={<ChevronRight size={14} />}
                        component={Link}
                        to="/library/browse/albums"
                        sx={{ textTransform: 'none', fontSize: 12 }}
                    >
                        All albums
                    </Button>
                }
            />
            <Box
                sx={(theme) => ({
                    display: 'grid',
                    gap: 1,
                    gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
                    [theme.breakpoints.down('tablet')]: {
                        gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))',
                    },
                })}
            >
                {albums.slice(0, 8).map((album) => (
                    <AlbumCard key={album.id} album={album} />
                ))}
            </Box>
        </Box>
    );
}

function AlbumCard({ album }: { album: AlbumResponseMinimal }) {
    return (
        <Link
            to="/library/album/$albumId"
            params={{ albumId: album.id }}
            style={{ textDecoration: 'none', color: 'inherit' }}
        >
            <Box
                sx={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 0.5,
                    borderRadius: 1,
                    overflow: 'hidden',
                    border: '1px solid',
                    borderColor: 'divider',
                    transition: 'border-color 0.15s',
                    '&:hover': { borderColor: 'primary.main' },
                }}
            >
                <CoverArt
                    type="album"
                    beetsId={album.id}
                    sx={{ width: '100%', aspectRatio: '1', objectFit: 'cover', display: 'block' }}
                />
                <Box sx={{ px: 1, pb: 1 }}>
                    <Typography
                        variant="body2"
                        fontWeight={600}
                        sx={{ lineHeight: 1.2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    >
                        {album.name || '[Unknown]'}
                    </Typography>
                    {album.added && (
                        <Typography variant="caption" color="text.disabled">
                            {relativeTime(album.added)}
                        </Typography>
                    )}
                </Box>
            </Box>
        </Link>
    );
}

/* ─────────────────────────── Artists Section ────────────────────────── */

function earliestAddedDate(artist: Artist) {
    return [artist.first_album_added, artist.first_item_added]
        .filter((d) => d instanceof Date)
        .reduce((min, d) => (d < min ? d : min));
}

function ArtistsSection() {
    const { data: artists } = useSuspenseQuery(artistsQueryOptions());

    const topArtists = useMemo(
        () => artists.filter((a) => a.item_count > 0).toSorted((a, b) => b.item_count - a.item_count).slice(0, 12),
        [artists]
    );
    const recentArtists = useMemo(
        () => artists.toSorted((a, b) => earliestAddedDate(b).getTime() - earliestAddedDate(a).getTime()).slice(0, 8),
        [artists]
    );

    return (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <Box>
                <SectionHeader
                    icon={<User2Icon size={16} />}
                    title="Top Artists"
                    action={
                        <Button
                            size="small"
                            endIcon={<ChevronRight size={14} />}
                            component={Link}
                            to="/library/browse/artists"
                            sx={{ textTransform: 'none', fontSize: 12 }}
                        >
                            All artists
                        </Button>
                    }
                />
                <Box sx={{ display: 'flex', flexDirection: 'column' }}>
                    {topArtists.map((artist) => (
                        <ArtistRow key={artist.artist} artist={artist} showTracks />
                    ))}
                </Box>
            </Box>

            <Box>
                <SectionHeader
                    icon={<ClockIcon size={16} />}
                    title="Recently Added"
                />
                <Box sx={{ display: 'flex', flexDirection: 'column' }}>
                    {recentArtists.map((artist) => (
                        <ArtistRow key={artist.artist} artist={artist} showDate />
                    ))}
                </Box>
            </Box>
        </Box>
    );
}

function ArtistRow({
    artist,
    showTracks,
    showDate,
}: {
    artist: Artist;
    showTracks?: boolean;
    showDate?: boolean;
}) {
    const theme = useTheme();
    return (
        <Link
            to="/library/browse/artists/$artist"
            params={{ artist: artist.artist }}
            style={{ textDecoration: 'none', color: 'inherit' }}
        >
            <Box
                sx={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    px: 1,
                    py: 0.75,
                    borderRadius: 0.5,
                    '&:hover': { backgroundColor: 'action.hover' },
                    gap: 1,
                }}
            >
                <Typography
                    variant="body2"
                    sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: '1 1 0' }}
                >
                    {artist.artist}
                </Typography>
                {showTracks && (
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, color: 'text.disabled', flexShrink: 0 }}>
                        <AudioLinesIcon size={12} />
                        <Typography variant="caption">{artist.item_count}</Typography>
                    </Box>
                )}
                {showDate && (
                    <Typography variant="caption" color="text.disabled" sx={{ flexShrink: 0 }}>
                        {relativeTime(earliestAddedDate(artist))}
                    </Typography>
                )}
            </Box>
        </Link>
    );
}

/* ─────────────────────────── Shared components ─────────────────────── */

function SectionHeader({
    icon,
    title,
    action,
}: {
    icon: React.ReactNode;
    title: string;
    action?: React.ReactNode;
}) {
    return (
        <Box
            sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                mb: 1.5,
                pb: 0.75,
                borderBottom: '1px solid',
                borderColor: 'divider',
            }}
        >
            <Box sx={{ color: 'text.disabled', display: 'flex' }}>{icon}</Box>
            <Typography variant="subtitle2" fontWeight={700} sx={{ flex: 1 }}>
                {title}
            </Typography>
            {action}
        </Box>
    );
}
