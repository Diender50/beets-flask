import { useEffect, useMemo, useRef, useState } from 'react';
import {
    Badge,
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Box,
    BoxProps,
    Chip,
    Alert,
    CircularProgress,
    Checkbox,
    Collapse,
    Divider,
    FormControl,
    FormControlLabel,
    FormGroup,
    IconButton,
    InputLabel,
    List as MuiList,
    MenuItem,
    Select,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableRow,
    Tooltip,
    ToggleButton,
    ToggleButtonGroup,
    Typography,
    useTheme,
} from '@mui/material';
import { CheckIcon, ChevronDownIcon, ChevronRightIcon, DownloadIcon, RefreshCw, XCircleIcon } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useQuery, useSuspenseQuery } from '@tanstack/react-query';
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router';

import {
    Album,
    albumsByArtistQueryOptions,
    artistQueryOptions,
    fetchMissingAlbumsByArtist,
    Item,
    itemsByArtistQueryOptions,
    MissingAlbum,
    missingAlbumsByArtistQueryOptions,
    missingAlbumTracksQueryOptions,
} from '@/api/library';
import {
    cleanupSlskdSearches,
    DownloadQuality,
    DownloadSuggestion,
    getDownloadJob,
    getDownloadSuggestions,
    startBatchDownload,
    startDownload,
} from '@/api/discovery';
import { AlbumIcon, ArtistIcon, TrackIcon } from '@/components/common/icons';
import { Search } from '@/components/common/inputs/search';
import { CoverArt } from '@/components/library/coverArt';

export const Route = createFileRoute('/library/browse/artists/$artist')({
    loader: async (opts) => {
        const p1 = opts.context.queryClient.ensureQueryData(
            albumsByArtistQueryOptions(opts.params.artist, false, true)
        );
        const p2 = opts.context.queryClient.ensureQueryData(
            artistQueryOptions(opts.params.artist)
        );
        const p3 = opts.context.queryClient.ensureQueryData(
            itemsByArtistQueryOptions(opts.params.artist, true)
        );
        await Promise.all([p1, p2, p3]);
    },
    component: RouteComponent,
});

function RouteComponent() {
    const params = Route.useParams();

    const { data: albums } = useSuspenseQuery(
        albumsByArtistQueryOptions(params.artist, false, true)
    );
    const { data: items } = useSuspenseQuery(
        itemsByArtistQueryOptions(params.artist, true)
    );

    return (
        <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100%', height: '100%' }}>
            <ArtistHeader
                sx={(theme) => ({
                    [theme.breakpoints.down('laptop')]: {
                        background: `linear-gradient(to bottom, transparent 0%, ${theme.palette.background.paper} 100%)`,
                    },
                })}
            />
            <Divider sx={{ backgroundColor: 'primary.muted' }} />
            <Viewer
                albums={albums}
                items={items}
                artist={params.artist}
                sx={(theme) => ({
                    flex: '1 1 auto',
                    minHeight: 0,
                    height: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    overflow: 'visible',
                    [theme.breakpoints.down('laptop')]: {
                        background: `linear-gradient(to bottom, ${theme.palette.background.paper} 0%, transparent 100%)`,
                    },
                })}
            />
        </Box>
    );
}

function ArtistHeader({ sx, ...props }: BoxProps) {
    const params = Route.useParams();
    const { data: artist } = useSuspenseQuery(artistQueryOptions(params.artist));

    const theme = useTheme();

    const nAlbums = artist.album_count;
    const nTracks = artist.item_count;

    return (
        <Box
            sx={[
                {
                    display: 'flex',
                    gap: 2,
                    alignItems: 'center',
                    padding: 2,
                },
                ...(Array.isArray(sx) ? sx : [sx]),
            ]}
            {...props}
        >
            <Link to="/library/browse/artists">
                <Box
                    sx={{
                        display: 'flex',
                        alignItems: 'center',
                        height: '100%',
                    }}
                >
                    <ArtistIcon size={40} color={theme.palette.primary.main} />
                </Box>
            </Link>
            <Box>
                <Typography variant="h5" fontWeight="bold" lineHeight={1}>
                    {artist.artist}
                </Typography>
                <Box
                    sx={{
                        display: 'flex',
                        gap: 2,
                        p: 0.5,
                        color: 'text.secondary',
                    }}
                >
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                        <AlbumIcon size={theme.iconSize.md} />
                        <Typography variant="body2">
                            {nAlbums} Album{nAlbums !== 1 ? 's' : ''}
                        </Typography>
                    </Box>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                        <TrackIcon size={theme.iconSize.md} />
                        <Typography variant="body2">
                            {nTracks} Track{nTracks !== 1 ? 's' : ''}
                        </Typography>
                    </Box>
                </Box>
            </Box>
        </Box>
    );
}

function Viewer({
    albums,
    items,
    artist,
    sx,
    ...props
}: {
    albums: Album<false, true>[];
    items: Item<true>[];
    artist: string;
} & BoxProps) {
    const theme = useTheme();
    const queryClient = useQueryClient();
    const [selected, setSelected] = useState<'albums' | 'missing'>('albums');
    const [filter, setFilter] = useState('');
    const [albumTypeFilter, setAlbumTypeFilter] = useState<string | null>(null);
    const [isRefreshing, setIsRefreshing] = useState(false);

    const missingAlbumsQuery = useQuery({
        ...missingAlbumsByArtistQueryOptions(artist),
        enabled: selected === 'missing',
    });
    const missingAlbums = missingAlbumsQuery.data ?? [];

    const handleRefreshMissing = async () => {
        setIsRefreshing(true);
        try {
            const fresh = await fetchMissingAlbumsByArtist(artist, true);
            queryClient.setQueryData(missingAlbumsByArtistQueryOptions(artist).queryKey, fresh);
            void queryClient.invalidateQueries({ queryKey: ['artists'] });
        } finally {
            setIsRefreshing(false);
        }
    };

    const albumIds = useMemo(() => new Set(albums.map((a) => a.id)), [albums]);

    const albumTypes = useMemo(() => {
        const types = new Set<string>();
        for (const album of albums) {
            if (album.albumtype) types.add(album.albumtype);
        }
        return [...types].sort();
    }, [albums]);

    const filteredAlbums = useMemo(() => {
        return albums.filter((album) => {
            const matchesText = !filter || album.name.toLowerCase().includes(filter.toLowerCase());
            const matchesType = !albumTypeFilter || album.albumtype === albumTypeFilter;
            return matchesText && matchesType;
        });
    }, [albums, filter, albumTypeFilter]);

    const filteredMissingAlbums = useMemo(() => {
        if (!filter) {
            return missingAlbums;
        }
        return missingAlbums.filter((album) => {
            return album.album.toLowerCase().includes(filter.toLowerCase());
        });
    }, [missingAlbums, filter]);

    const trackCountByAlbumId = useMemo(() => {
        const map = new Map<number, number>();
        for (const item of items) {
            if (albumIds.has(item.album_id)) {
                map.set(item.album_id, (map.get(item.album_id) ?? 0) + 1);
            }
        }
        return map;
    }, [items, albumIds]);

    // Items where this artist is featured but is NOT the albumartist
    const featuredByAlbum = useMemo(() => {
        const map = new Map<number, { albumName: string; albumArtist: string; tracks: Item<true>[] }>();
        for (const item of items) {
            if (albumIds.has(item.album_id)) continue;
            if (!map.has(item.album_id)) {
                map.set(item.album_id, {
                    albumName: item.album,
                    albumArtist: item.albumartist,
                    tracks: [],
                });
            }
            map.get(item.album_id)!.tracks.push(item);
        }
        return map;
    }, [items, albumIds]);

    const filteredFeaturedByAlbum = useMemo(() => {
        if (!filter) return featuredByAlbum;
        const result = new Map<number, { albumName: string; albumArtist: string; tracks: Item<true>[] }>();
        for (const [albumId, entry] of featuredByAlbum) {
            const matchAlbum = entry.albumName.toLowerCase().includes(filter.toLowerCase());
            const matchArtist = entry.albumArtist.toLowerCase().includes(filter.toLowerCase());
            const matchTrack = entry.tracks.some((t) =>
                t.name.toLowerCase().includes(filter.toLowerCase())
            );
            if (matchAlbum || matchArtist || matchTrack) {
                result.set(albumId, entry);
            }
        }
        return result;
    }, [featuredByAlbum, filter]);

    const nAlbumsRemovedByFilter = albums.length - filteredAlbums.length;
    const nMissingRemovedByFilter =
        missingAlbums.length - filteredMissingAlbums.length;

    const nRemovedByFilter =
        selected === 'albums' ? nAlbumsRemovedByFilter : nMissingRemovedByFilter;

    return (
        <Box
            sx={[
                {
                    display: 'flex',
                    flexDirection: 'column',
                    minHeight: 0,
                    height: '100%',
                    overflow: 'hidden',
                },
                ...(Array.isArray(sx) ? sx : [sx]),
            ]}
            {...props}
        >
            <Box
                sx={{
                    width: '100%',
                    padding: 2,
                    height: 'min-content',
                    overflow: 'visible',
                }}
            >
                <Box
                    sx={{
                        display: 'flex',
                        gap: 2,
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        flexWrap: 'wrap',
                    }}
                >
                    <Search
                        value={filter}
                        setValue={setFilter}
                        size="small"
                        sx={{
                            flex: '1 1 auto',
                            maxWidth: 300,
                        }}
                    />
                    <Box
                        sx={{
                            display: 'flex',
                            gap: 1,
                            alignItems: 'center',
                        }}
                    >
                        <ToggleButtonGroup
                            value={selected}
                            onChange={(
                                _e: React.MouseEvent<HTMLElement>,
                                v: 'albums' | 'missing' | null
                            ) => {
                                if (v) setSelected(v);
                            }}
                            color="primary"
                            exclusive
                            aria-label="Filter type"
                        >
                            <ToggleButton value="albums">
                                <AlbumIcon size={theme.iconSize.lg} />
                            </ToggleButton>
                            <ToggleButton value="missing">
                                {missingAlbumsQuery.data ? (
                                    <Badge
                                        badgeContent={missingAlbums.length}
                                        color="error"
                                        max={99}
                                        sx={{ '& .MuiBadge-badge': { fontSize: 10, height: 16, minWidth: 16 } }}
                                    >
                                        <Typography variant="body2" sx={{ pr: missingAlbums.length > 0 ? 1 : 0 }}>
                                            Missing
                                        </Typography>
                                    </Badge>
                                ) : (
                                    <Typography variant="body2">Missing</Typography>
                                )}
                            </ToggleButton>
                        </ToggleButtonGroup>
                        {selected === 'missing' && (
                            <Tooltip title="Recompute from MusicBrainz & Deezer (bypass cache)">
                                <IconButton
                                    size="small"
                                    onClick={() => void handleRefreshMissing()}
                                    disabled={isRefreshing || missingAlbumsQuery.isLoading}
                                >
                                    {isRefreshing
                                        ? <CircularProgress size={16} />
                                        : <RefreshCw size={16} />}
                                </IconButton>
                            </Tooltip>
                        )}
                    </Box>
                </Box>
                {selected === 'albums' && albumTypes.length > 1 && (
                    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 1 }}>
                        <Chip
                            label="All"
                            size="small"
                            variant={albumTypeFilter === null ? 'filled' : 'outlined'}
                            color={albumTypeFilter === null ? 'primary' : 'default'}
                            onClick={() => setAlbumTypeFilter(null)}
                        />
                        {albumTypes.map((type) => (
                            <Chip
                                key={type}
                                label={type}
                                size="small"
                                variant={albumTypeFilter === type ? 'filled' : 'outlined'}
                                color={albumTypeFilter === type ? 'primary' : 'default'}
                                onClick={() =>
                                    setAlbumTypeFilter(albumTypeFilter === type ? null : type)
                                }
                            />
                        ))}
                    </Box>
                )}
                <Typography
                    variant="caption"
                    color="text.secondary"
                    visibility={nRemovedByFilter > 0 ? 'visible' : 'hidden'}
                >
                    {nRemovedByFilter}{' '}
                    {nRemovedByFilter > 1
                        ? selected
                        : selected.replace('s', '')}{' '}
                    hidden by filter
                </Typography>
            </Box>
            <Box
                sx={{
                    overflow: 'hidden',
                    flex: '1 1 auto',
                    paddingInline: 2,
                    minHeight: 0,
                }}
            >
                {selected === 'albums' && (
                    <AlbumsViewer albums={filteredAlbums} trackCountByAlbumId={trackCountByAlbumId} />
                )}
                {selected === 'albums' && filteredFeaturedByAlbum.size > 0 && (
                    <FeaturedOnViewer featuredByAlbum={filteredFeaturedByAlbum} />
                )}
                {selected === 'missing' && (
                    missingAlbumsQuery.isLoading ? (
                        <Box
                            sx={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                height: '100%',
                            }}
                        >
                            <CircularProgress size={20} />
                        </Box>
                    ) : (
                        <MissingAlbumsViewer
                            albums={filteredMissingAlbums}
                            artist={artist}
                            isRefreshing={isRefreshing}
                            onRefresh={handleRefreshMissing}
                        />
                    )
                )}
            </Box>
        </Box>
    );
}

function AlbumsViewer({
    albums,
    trackCountByAlbumId,
}: {
    albums: Album<false, true>[];
    trackCountByAlbumId: Map<number, number>;
}) {
    const navigate = useNavigate();
    const grouped = useMemo(() => {
        const map = new Map<string, Album<false, true>[]>();
        for (const album of albums) {
            const type = album.albumtype ?? 'album';
            if (!map.has(type)) map.set(type, []);
            map.get(type)!.push(album);
        }
        return map;
    }, [albums]);

    const orderedTypes = [
        ...RELEASE_TYPE_ORDER.filter((t) => grouped.has(t)),
        ...[...grouped.keys()].filter((t) => !RELEASE_TYPE_ORDER.includes(t)),
    ];

    if (albums.length === 0) {
        return (
            <Box sx={{ py: 2, px: 1 }}>
                <Typography variant="body1" color="text.secondary">
                    No albums found.
                </Typography>
            </Box>
        );
    }

    return (
        <Box sx={{ overflow: 'auto', height: '100%', display: 'flex', flexDirection: 'column' }}>
            {orderedTypes.map((type) => (
                <Box key={type} sx={{ mb: 3 }}>
                    <Typography
                        variant="subtitle2"
                        color="text.secondary"
                        sx={{
                            px: 1,
                            py: 0.5,
                            position: 'sticky',
                            top: 0,
                            zIndex: 1,
                            backgroundColor: 'background.paper',
                            borderBottom: 1,
                            borderColor: 'divider',
                        }}
                    >
                        {RELEASE_TYPE_LABELS[type] ?? type} ({grouped.get(type)!.length})
                    </Typography>
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell sx={{ width: 44 }} />
                                <TableCell>Album</TableCell>
                                <TableCell sx={{ width: 60 }} align="right">Tracks</TableCell>
                                <TableCell sx={{ width: 60 }}>Year</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {grouped.get(type)!.map((album) => (
                                <TableRow
                                    key={album.id}
                                    hover
                                    sx={{ cursor: 'pointer' }}
                                    onClick={() => void navigate({ to: '/library/album/$albumId', params: { albumId: album.id } })}
                                >
                                    <TableCell sx={{ p: 0.5, width: 44 }}>
                                        <CoverArt
                                            type="album"
                                            beetsId={album.id}
                                            sx={{
                                                width: 36,
                                                height: 36,
                                                objectFit: 'cover',
                                                borderRadius: 0.5,
                                                display: 'block',
                                            }}
                                        />
                                    </TableCell>
                                    <TableCell>
                                        <Link
                                            to="/library/album/$albumId"
                                            params={{ albumId: album.id }}
                                            onClick={(e) => e.stopPropagation()}
                                        >
                                            {album.name}
                                        </Link>
                                    </TableCell>
                                    <TableCell align="right" sx={{ color: 'text.secondary' }}>
                                        {trackCountByAlbumId.get(album.id) ?? '-'}
                                    </TableCell>
                                    <TableCell>{album.year ?? '-'}</TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </Box>
            ))}
        </Box>
    );
}

function FeaturedOnViewer({
    featuredByAlbum,
}: {
    featuredByAlbum: Map<number, { albumName: string; albumArtist: string; tracks: Item<true>[] }>;
}) {
    const navigate = useNavigate();
    return (
        <Box sx={{ mt: 2, mb: 3 }}>
            <Typography
                variant="subtitle2"
                color="text.secondary"
                sx={{
                    px: 1,
                    py: 0.5,
                    position: 'sticky',
                    top: 0,
                    zIndex: 1,
                    backgroundColor: 'background.paper',
                    borderBottom: 1,
                    borderColor: 'divider',
                }}
            >
                Featured on ({featuredByAlbum.size})
            </Typography>
            {[...featuredByAlbum.entries()].map(([albumId, entry]) => (
                <Box key={albumId} sx={{ mb: 2 }}>
                    <Box
                        sx={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 1,
                            px: 1,
                            py: 0.5,
                            cursor: 'pointer',
                            '&:hover': { backgroundColor: 'action.hover' },
                            borderRadius: 1,
                        }}
                        onClick={() =>
                            void navigate({
                                to: '/library/album/$albumId',
                                params: { albumId: albumId },
                            })
                        }
                    >
                        <CoverArt
                            type="album"
                            beetsId={albumId}
                            sx={{ width: 36, height: 36, objectFit: 'cover', borderRadius: 0.5, flexShrink: 0 }}
                        />
                        <Box>
                            <Typography variant="body2" fontWeight="medium">
                                {entry.albumName}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                                {entry.albumArtist}
                            </Typography>
                        </Box>
                    </Box>
                    <Table size="small">
                        <TableBody>
                            {entry.tracks.map((track) => (
                                <TableRow key={track.id} hover sx={{ cursor: 'pointer' }}
                                    onClick={() =>
                                        void navigate({
                                            to: '/library/album/$albumId',
                                            params: { albumId: track.album_id },
                                        })
                                    }
                                >
                                    <TableCell sx={{ pl: 2, color: 'text.secondary', width: 32 }}>
                                        <TrackIcon size={14} />
                                    </TableCell>
                                    <TableCell>{track.name}</TableCell>
                                    <TableCell sx={{ color: 'text.secondary', width: 200 }}>
                                        {track.artist}
                                    </TableCell>
                                    <TableCell sx={{ width: 60, color: 'text.secondary' }} align="right">
                                        {track.year ?? '-'}
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </Box>
            ))}
        </Box>
    );
}

const RELEASE_TYPE_LABELS: Record<string, string> = {
    album: 'Albums',
    ep: 'EPs',
    single: 'Singles',
    live: 'Live',
    compilation: 'Compilations',
    remix: 'Remixes',
    soundtrack: 'Soundtracks',
    other: 'Other',
};

const RELEASE_TYPE_ORDER = [
    'album',
    'ep',
    'single',
    'live',
    'compilation',
    'remix',
    'soundtrack',
    'other',
];

function formatDuration(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
}

function TrackList({ releaseId }: { releaseId: string }) {
    const { data: tracks, isLoading } = useQuery(missingAlbumTracksQueryOptions(releaseId));

    if (isLoading) {
        return (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 1.5 }}>
                <CircularProgress size={20} />
            </Box>
        );
    }
    if (!tracks || tracks.length === 0) {
        return (
            <Typography variant="body2" sx={{ py: 1.5, px: 2, color: 'text.secondary' }}>
                No track info available
            </Typography>
        );
    }
    return (
        <Table size="small" sx={{ tableLayout: 'fixed' }}>
            <TableBody>
                {tracks.map((t, i) => (
                    <TableRow key={i} sx={{ '&:last-child td': { borderBottom: 0 } }}>
                        <TableCell sx={{ width: 32, color: 'text.secondary', textAlign: 'right', pr: 1.5 }}>
                            {t.track_position ?? i + 1}
                        </TableCell>
                        <TableCell>{t.title}</TableCell>
                        <TableCell sx={{ width: 64, textAlign: 'right', color: 'text.secondary' }}>
                            {t.duration ? formatDuration(t.duration) : ''}
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    );
}

function MissingAlbumTrackCount({ album }: { album: MissingAlbum }) {
    const releaseId = album.mb_releasegroupid;
    const isMusicBrainzRelease = !!releaseId && !releaseId.startsWith('deezer:');
    const shouldFetchCount =
        isMusicBrainzRelease && (album.track_count === null || album.track_count === undefined);

    const { data: tracks, isLoading } = useQuery({
        ...missingAlbumTracksQueryOptions(releaseId ?? ''),
        enabled: shouldFetchCount,
    });

    if (album.track_count !== null && album.track_count !== undefined) {
        return <>{album.track_count}</>;
    }
    if (!releaseId) {
        return <>-</>;
    }
    if (isLoading) {
        return <CircularProgress size={12} />;
    }
    if (tracks && tracks.length > 0) {
        return <>{tracks.length}</>;
    }
    return <>-</>;
}

function useExpectedTrackCount(album: MissingAlbum): number | null {
    const releaseId = album.mb_releasegroupid;
    const isMusicBrainzRelease = !!releaseId && !releaseId.startsWith('deezer:');
    const shouldFetchCount =
        isMusicBrainzRelease && (album.track_count === null || album.track_count === undefined);

    const { data: tracks } = useQuery({
        ...missingAlbumTracksQueryOptions(releaseId ?? ''),
        enabled: shouldFetchCount,
    });

    if (album.track_count !== null && album.track_count !== undefined) {
        return album.track_count;
    }
    if (tracks && tracks.length > 0) {
        return tracks.length;
    }
    return null;
}

function asNumber(value: unknown): number | null {
    if (typeof value === 'number' && Number.isFinite(value)) {
        return value;
    }
    if (typeof value === 'string' && value.trim()) {
        const parsed = Number(value);
        if (Number.isFinite(parsed)) {
            return parsed;
        }
    }
    return null;
}

function deemixDetailsToQuality(details: Record<string, unknown>): DownloadQuality {
    const container = String(details.container ?? '').toLowerCase();
    const kbps = typeof details.kbps === 'number' ? details.kbps : null;
    if (container === 'flac' || (kbps !== null && kbps >= 1000)) return 'flac';
    if (kbps !== null && kbps >= 256) return '320';
    return '128';
}

function trackMatchColor(resultTrackCount: number | null, expectedTrackCount: number | null) {
    if (resultTrackCount === null || expectedTrackCount === null || expectedTrackCount <= 0) {
        return 'text.secondary';
    }
    if (resultTrackCount === expectedTrackCount) {
        return 'success.main';
    }
    if (resultTrackCount < expectedTrackCount * 0.7) {
        return 'error.main';
    }
    return 'warning.main';
}

function speedMatchColor(
    uploadSpeedBytes: number | null,
    queueLength: number | null,
    hasFreeUploadSlot: boolean,
) {
    void queueLength;
    void hasFreeUploadSlot;
    const speedMBs = uploadSpeedBytes !== null ? uploadSpeedBytes / 1_000_000 : null;
    if (speedMBs === null) return 'text.secondary';
    if (speedMBs < 1) return 'error.main';
    if (speedMBs <= 5) return 'warning.main';
    return 'success.main';
}

function queueMatchColor(queueLength: number | null) {
    if (queueLength === null || queueLength <= 0) return 'text.secondary';
    if (queueLength < 100) return 'warning.main';
    return 'error.main';
}

function DownloadButton({ album, artist }: { album: MissingAlbum; artist: string }) {
    const deezerId = album.mb_releasegroupid?.startsWith('deezer:')
        ? album.mb_releasegroupid.slice(7)
        : undefined;
    const releaseId = !deezerId ? (album.mb_releasegroupid ?? undefined) : undefined;
    const tracklistReleaseId = album.mb_releasegroupid ?? (deezerId ? `deezer:${deezerId}` : undefined);
    const expectedTrackCount = useExpectedTrackCount(album);
    const [jobId, setJobId] = useState<string | null>(null);
    const [open, setOpen] = useState(false);
    const { data: expectedTracks = [] } = useQuery({
        ...missingAlbumTracksQueryOptions(tracklistReleaseId ?? ''),
        enabled: open && !!tracklistReleaseId,
    });
    const [searchCycle, setSearchCycle] = useState(0);
    const [expandedChoiceKey, setExpandedChoiceKey] = useState<string | null>(null);
    const [suggestionChoices, setSuggestionChoices] = useState<DownloadSuggestion[]>([]);
    const [slskdLoading, setSlskdLoading] = useState(false);
    const [deemixLoading, setDeemixLoading] = useState(false);
    const [squidwtfLoading, setSquidwtfLoading] = useState(false);
    const [suggestionErrors, setSuggestionErrors] = useState<string[]>([]);
    const [errorProviders, setErrorProviders] = useState<Set<string>>(new Set());
    const [providerResultCount, setProviderResultCount] = useState<Partial<Record<string, number>>>({});
    const [hiddenProviders, setHiddenProviders] = useState<Set<string>>(new Set());
    const [selectedQualities, setSelectedQualities] = useState<Set<string>>(new Set(['FLAC']));
    const [retryTrigger, setRetryTrigger] = useState<{ provider: 'slskd' | 'deemix' | 'squidwtf'; cycle: number } | null>(null);
    const searchAbortRef = useRef<AbortController[] | null>(null);

    const cleanupSlskdSearchesForDialog = () => {
        const searchIds = suggestionChoices
            .filter((choice) => choice.provider === 'slskd')
            .map((choice) => String(choice.details.searchId ?? ''))
            .filter((value) => value.length > 0);
        void cleanupSlskdSearches({
            artist,
            album: album.album,
            searchIds,
        }).catch(() => undefined);
    };

    const closeDialog = (opts?: { cleanupSlskd?: boolean }) => {
        setOpen(false);
        searchAbortRef.current?.forEach((ctrl) => ctrl.abort());
        searchAbortRef.current = null;
        if (opts?.cleanupSlskd !== false) {
            cleanupSlskdSearchesForDialog();
        }
    };

    const openDialog = () => {
        setSearchCycle((prev) => prev + 1);
        setOpen(true);
    };

    useEffect(() => {
        if (!open) {
            return;
        }

        const slskdCtrl = new AbortController();
        const deemixCtrl = new AbortController();
        const squidwtfCtrl = new AbortController();
        // cancelled guards against React Strict Mode's double-invocation:
        // the first effect run's async callbacks must not update state after
        // the cleanup fires and the second run starts fresh.
        let cancelled = false;

        searchAbortRef.current = [slskdCtrl, deemixCtrl, squidwtfCtrl];

        setSuggestionChoices([]);
        setSuggestionErrors([]);
        setErrorProviders(new Set());
        setProviderResultCount({});
        setHiddenProviders(new Set());
        setSelectedQualities(new Set(['FLAC']));
        setSlskdLoading(true);
        setDeemixLoading(true);
        setSquidwtfLoading(true);

        const mergeChoices = (incoming: DownloadSuggestion[]) => {
            if (cancelled) return;
            setSuggestionChoices((prev) => {
                const merged = [...prev, ...incoming];
                const seen = new Set<string>();
                const deduped = merged.filter((choice) => {
                    const key = `${choice.provider}:${String(choice.details.deezer_id ?? '')}:${String(choice.details.folder ?? '')}:${choice.title}`;
                    if (seen.has(key)) return false;
                    seen.add(key);
                    return true;
                });
                deduped.sort((a, b) => b.score - a.score);
                return deduped;
            });
        };

        const runProvider = async (
            provider: 'slskd' | 'deemix' | 'squidwtf',
            signal: AbortSignal,
            setLoading: (v: boolean) => void,
        ) => {
            try {
                const data = await getDownloadSuggestions({
                    artist,
                    album: album.album,
                    provider,
                    signal,
                    expected_track_count: expectedTrackCount ?? undefined,
                });
                mergeChoices(data.results ?? []);
                if (!cancelled) setProviderResultCount((prev: Partial<Record<string, number>>) => ({ ...prev, [provider]: data.results?.length ?? 0 }));
            } catch (err) {
                // Abort on popup close (or Strict Mode cleanup) should be silent.
                if (err instanceof DOMException && err.name === 'AbortError') {
                    return;
                }
                if (!cancelled) {
                    setSuggestionErrors((prev) => [
                        ...prev,
                        `${provider}: ${(err as Error)?.message ?? 'request failed'}`,
                    ]);
                    setErrorProviders((prev: Set<string>) => new Set([...prev, provider]));
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        };

        void runProvider('slskd', slskdCtrl.signal, setSlskdLoading);
        void runProvider('deemix', deemixCtrl.signal, setDeemixLoading);
        void runProvider('squidwtf', squidwtfCtrl.signal, setSquidwtfLoading);

        return () => {
            cancelled = true;
            slskdCtrl.abort();
            deemixCtrl.abort();
            squidwtfCtrl.abort();
        };
    }, [open, searchCycle, artist, album.album]);

    // Retry a single provider (0-result re-search)
    useEffect(() => {
        if (!retryTrigger || !open) return;
        const { provider } = retryTrigger;
        const ctrl = new AbortController();
        let cancelled = false;

        const setLoading = provider === 'slskd' ? setSlskdLoading : provider === 'deemix' ? setDeemixLoading : setSquidwtfLoading;
        setSuggestionChoices((prev) => prev.filter((c) => c.provider !== provider));
        setProviderResultCount((prev: Partial<Record<string, number>>) => { const n = { ...prev }; delete n[provider]; return n; });
        setErrorProviders((prev) => { const n = new Set(prev); n.delete(provider); return n; });
        setSuggestionErrors((prev) => prev.filter((e) => !e.startsWith(`${provider}:`)));
        setLoading(true);

        const run = async () => {
            try {
                const data = await getDownloadSuggestions({ artist, album: album.album, provider, signal: ctrl.signal, expected_track_count: expectedTrackCount ?? undefined });
                if (!cancelled) {
                    setSuggestionChoices((prev) => {
                        const merged = [...prev, ...(data.results ?? [])];
                        const seen = new Set<string>();
                        return merged.filter((c) => {
                            const k = `${c.provider}:${String(c.details.deezer_id ?? '')}:${String(c.details.folder ?? '')}:${c.title}`;
                            if (seen.has(k)) return false;
                            seen.add(k);
                            return true;
                        }).sort((a, b) => b.score - a.score);
                    });
                    setProviderResultCount((prev: Partial<Record<string, number>>) => ({ ...prev, [provider]: data.results?.length ?? 0 }));
                }
            } catch (err) {
                if (err instanceof DOMException && err.name === 'AbortError') return;
                if (!cancelled) {
                    setSuggestionErrors((prev) => [...prev, `${provider}: ${(err as Error)?.message ?? 'request failed'}`]);
                    setErrorProviders((prev) => new Set([...prev, provider]));
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        };
        void run();
        return () => { cancelled = true; ctrl.abort(); };
    }, [retryTrigger, open, artist, album.album]);

    const suggestionLoading = slskdLoading || deemixLoading || squidwtfLoading;
    const suggestionError = suggestionErrors.join(' | ');

    const availableQualities = useMemo(() => {
        const set = new Set<string>();
        for (const c of suggestionChoices) {
            const q = c.provider === 'slskd'
                ? String(c.details.extension ?? '').toUpperCase().replace('.', '')
                : String(c.details.container ?? '').toUpperCase();
            if (q) set.add(q);
        }
        return [...set].sort();
    }, [suggestionChoices]);

    const visibleChoices = useMemo(() => suggestionChoices.filter((c) => {
        if (hiddenProviders.has(c.provider)) return false;
        if (selectedQualities.size > 0) {
            const q = c.provider === 'slskd'
                ? String(c.details.extension ?? '').toUpperCase().replace('.', '')
                : String(c.details.container ?? '').toUpperCase();
            if (!selectedQualities.has(q)) return false;
        }
        return true;
    }), [suggestionChoices, hiddenProviders, selectedQualities]);

    const mutation = useMutation({
        mutationFn: async (choice: DownloadSuggestion) => {
            cleanupSlskdSearchesForDialog();
            if (choice.provider === 'deemix') {
                return startDownload({
                    album: album.album,
                    artist,
                    provider: 'deemix',
                    deezer_id: String(choice.details.deezer_id ?? deezerId ?? ''),
                    release_id: releaseId,
                    quality: deemixDetailsToQuality(choice.details),
                });
            }
            if (choice.provider === 'squidwtf') {
                return startDownload({
                    album: album.album,
                    artist,
                    provider: 'squidwtf',
                    squid_album_id: String(choice.details.squid_album_id ?? ''),
                    release_id: releaseId,
                });
            }
            return startDownload({
                album: album.album,
                artist,
                provider: 'slskd',
                candidate: choice.details.candidate as Record<string, unknown>,
                release_id: releaseId,
            });
        },
        onSuccess: (job) => {
            setJobId(job.job_id);
            closeDialog({ cleanupSlskd: false });
        },
    });

    const { data: job } = useQuery({
        queryKey: ['downloadJob', jobId],
        queryFn: () => getDownloadJob(jobId ?? ''),
        enabled: !!jobId,
        refetchInterval: (query) => {
            const status = query.state.data?.status;
            return status === 'pending' || status === 'downloading' ? 2000 : false;
        },
    });

    const currentJob = job ?? mutation.data ?? null;
    const status = currentJob?.status;
    const provider = currentJob?.provider ?? 'auto';
    const selectedMatch = currentJob?.selected_match as Record<string, unknown> | null | undefined;
    const candidateList = currentJob?.provider_candidates as Array<Record<string, unknown>> | null | undefined;
    const stage = currentJob?.stage ?? null;
    const progressMessage = currentJob?.progress_message ?? null;
    const statusText =
        status === 'pending'
            ? 'Queued'
            : status === 'downloading'
              ? 'Working'
              : status === 'done'
                ? 'Done'
                : status === 'error'
                  ? 'Failed'
                  : 'Ready';

    const detailLines: string[] = [];
    if (stage) detailLines.push(`step: ${stage}`);
    if (progressMessage) detailLines.push(progressMessage);
    if (currentJob?.selection_reason) detailLines.push(currentJob.selection_reason);
    if (selectedMatch) {
        const providerName = String(selectedMatch.provider ?? provider);
        const label = providerName === 'deemix'
            ? `deemix ${String(selectedMatch.deezer_id ?? '')}`.trim()
            : providerName === 'squidwtf'
                ? `squidwtf ${String(selectedMatch.squid_album_id ?? '')}`.trim()
            : `slskd ${String(selectedMatch.filename ?? '')}`.trim();
        if (label.trim()) detailLines.push(`selected: ${label}`);
        const score = selectedMatch.score;
        if (typeof score === 'number') detailLines.push(`score: ${score.toFixed(3)}`);
    }
    if (candidateList?.length) {
        detailLines.push(`probed: ${candidateList.filter((entry) => entry.ok).map((entry) => entry.provider).join(', ')}`);
    }
    if (currentJob?.error) detailLines.push(`error: ${currentJob.error}`);
    if (currentJob?.output_path) detailLines.push(`dest: ${currentJob.output_path}`);

    const tooltipTitle = mutation.isError
        ? `Error: ${(mutation.error as Error)?.message ?? 'unknown'}`
        : 'Choose best result';

    const iconColor =
        status === 'done' ? 'success' : status === 'error' ? 'error' : status ? 'warning' : 'default';

    return (
        <Box sx={{ display: 'flex', justifyContent: 'center' }}>
            <Tooltip
                placement="left"
                title={
                    <Box>
                        <Typography variant="caption" sx={{ fontWeight: 700, display: 'block', mb: 0.25 }}>
                            {tooltipTitle}
                        </Typography>
                        {detailLines.slice(0, 4).map((line) => (
                            <Typography key={line} variant="caption" sx={{ display: 'block', lineHeight: 1.3 }}>
                                {line}
                            </Typography>
                        ))}
                    </Box>
                }
            >
                <span>
                    <Button
                        size="small"
                        variant={status === 'done' ? 'contained' : 'outlined'}
                        color={status === 'done' ? 'success' : status === 'error' ? 'error' : 'primary'}
                        onClick={openDialog}
                        disabled={mutation.isPending || status === 'pending' || status === 'downloading'}
                        startIcon={
                            mutation.isPending || status === 'pending' || status === 'downloading' ? (
                                <CircularProgress size={12} />
                            ) : status === 'done' ? (
                                <CheckIcon size={14} />
                            ) : status === 'error' ? (
                                <XCircleIcon size={14} />
                            ) : (
                                <DownloadIcon size={14} />
                            )
                        }
                        sx={{
                            minWidth: 86,
                            height: 28,
                            px: 1,
                            borderRadius: 1,
                            fontSize: 11,
                            textTransform: 'none',
                            fontWeight: 700,
                        }}
                    >
                        {statusText}
                    </Button>
                </span>
            </Tooltip>
            <Dialog open={open} onClose={closeDialog} fullWidth maxWidth="xs">
                <DialogTitle>Choose download result</DialogTitle>
                <DialogContent dividers>
                    <Box sx={{ display: 'flex', gap: 1, mb: 1.5, flexWrap: 'wrap', alignItems: 'center' }}>
                        {(
                            [
                                { key: 'slskd' as const, loading: slskdLoading },
                                { key: 'deemix' as const, loading: deemixLoading },
                                { key: 'squidwtf' as const, loading: squidwtfLoading },
                            ]
                        ).map(({ key, loading }) => {
                            const hasError = errorProviders.has(key);
                            const count = providerResultCount[key];
                            const isDone = !loading && !hasError && count !== undefined;
                            const hasResults = isDone && count > 0;
                            const isHidden = hiddenProviders.has(key);
                            return (
                                <Chip
                                    key={key}
                                    label={key}
                                    size="small"
                                    variant={loading || isHidden ? 'outlined' : 'filled'}
                                    color={loading ? 'default' : hasError ? 'error' : isHidden ? 'default' : key === 'deemix' ? 'primary' : key === 'squidwtf' ? 'success' : 'secondary'}
                                    icon={
                                        loading ? (
                                            <CircularProgress size={12} sx={{ ml: '6px !important' }} />
                                        ) : hasError ? (
                                            <XCircleIcon size={12} />
                                        ) : (
                                            <CheckIcon size={12} />
                                        )
                                    }
                                    onClick={isDone && !hasError ? () => {
                                        if (hasResults) {
                                            setHiddenProviders((prev: Set<string>) => {
                                                const next = new Set(prev);
                                                if (next.has(key)) next.delete(key); else next.add(key);
                                                return next;
                                            });
                                        } else {
                                            setRetryTrigger({ provider: key, cycle: Date.now() });
                                        }
                                    } : undefined}
                                    sx={{ cursor: isDone && !hasError ? 'pointer' : 'default' }}
                                />
                            );
                        })}
                        <Box sx={{ ml: 'auto', display: 'flex', gap: 1 }}>
                            {availableQualities.map((q: string) => {
                                const selected = selectedQualities.has(q);
                                const qColor = q === 'FLAC' ? 'info' : q === 'MP3' ? 'warning' : 'default';
                                return (
                                <Chip
                                    key={q}
                                    label={q}
                                    size="small"
                                    variant={selected ? 'filled' : 'outlined'}
                                    color={selected ? qColor : 'default'}
                                    onClick={() => setSelectedQualities((prev: Set<string>) => {
                                        const next = new Set(prev);
                                        if (next.has(q)) next.delete(q); else next.add(q);
                                        return next;
                                    })}
                                    sx={{ cursor: 'pointer', opacity: selected ? 1 : 0.5 }}
                                />
                                );
                            })}
                        </Box>
                    </Box>
                    {suggestionLoading && suggestionChoices.length === 0 ? (
                        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                            <CircularProgress size={24} />
                        </Box>
                    ) : suggestionChoices.length > 0 ? (
                        <>
                        <MuiList disablePadding>
                            {visibleChoices.map((choice: DownloadSuggestion, index: number) => (
                                (() => {
                                    const resultTrackCount = choice.provider === 'deemix'
                                        ? asNumber(choice.details.trackCount)
                                        : choice.provider === 'squidwtf'
                                            ? asNumber(choice.details.trackCount)
                                            : asNumber(choice.details.audioFileCount);
                                    const meanAudioBitrateKbps = choice.provider === 'slskd'
                                        ? asNumber(choice.details.meanAudioBitrateKbps)
                                        : null;
                                    const uploadSpeed = choice.provider === 'slskd'
                                        ? asNumber(choice.details.uploadSpeed)
                                        : null;
                                    const queueLength = choice.provider === 'slskd'
                                        ? asNumber(choice.details.queueLength)
                                        : null;
                                    const hasFreeUploadSlot = Boolean(choice.details.hasFreeUploadSlot);
                                    const container = choice.provider === 'deemix'
                                        ? String(choice.details.container ?? '-')
                                        : choice.provider === 'squidwtf'
                                            ? String(choice.details.container ?? '-')
                                        : String(choice.details.extension ?? '-').toUpperCase();
                                    const kbps = choice.provider === 'deemix'
                                        ? asNumber(choice.details.kbps)
                                        : choice.provider === 'squidwtf'
                                            ? asNumber(choice.details.kbps)
                                        : meanAudioBitrateKbps;
                                    const isSlskd = choice.provider === 'slskd';
                                    const bitDepth = isSlskd ? asNumber(choice.details.bitDepth) : null;
                                    const qualityLabel = (() => {
                                        if (container === '-') return container;
                                        if (container === 'FLAC') {
                                            if (bitDepth !== null && bitDepth > 0)
                                                return bitDepth >= 20 ? 'FLAC-24' : 'FLAC-16';
                                            if (choice.provider === 'deemix') return 'FLAC-16';
                                            if (kbps !== null) return kbps > 1500 ? 'FLAC-24' : 'FLAC-16';
                                            return 'FLAC';
                                        }
                                        if (kbps !== null && kbps > 0) {
                                            const steps = [8,16,24,32,40,48,56,64,80,96,112,128,160,192,224,256,320];
                                            const nearest = steps.reduce((a, b) => Math.abs(b - kbps) < Math.abs(a - kbps) ? b : a);
                                            return `${container}-${nearest}`;
                                        }
                                        return container;
                                    })();
                                    const trackColor = trackMatchColor(resultTrackCount, expectedTrackCount);
                                    const speedColor = speedMatchColor(uploadSpeed, queueLength, hasFreeUploadSlot);
                                    const queueColor = queueMatchColor(queueLength);
                                    const choiceKey = `${choice.provider}-${choice.title}-${index}`;
                                    const isExpanded = isSlskd && expandedChoiceKey === choiceKey;
                                    const audioExts = new Set(['flac', 'mp3', 'm4a', 'ogg', 'aac', 'wav', 'aiff', 'opus', 'wma']);
                                    const slskdAudioFiles = isSlskd
                                        ? (((choice.details.candidate as Record<string, unknown>)?.files as Array<Record<string, unknown>> | undefined) ?? [])
                                            .filter(f => audioExts.has(String(f.extension ?? '').toLowerCase().replace('.', '')))
                                        : [];
                                    const providerColor = choice.provider === 'deemix' ? 'primary.main' : choice.provider === 'squidwtf' ? 'success.main' : 'secondary.main';
                                    return (
                                <Box
                                    key={choiceKey}
                                    sx={{
                                        mb: 0.75,
                                        borderRadius: 1,
                                        border: 1,
                                        borderColor: isExpanded ? 'primary.main' : 'divider',
                                        overflow: 'hidden',
                                        '&:hover': { borderColor: isExpanded ? 'primary.main' : 'action.selected' },
                                        transition: 'border-color 0.15s',
                                    }}
                                >
                                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.5, py: 1 }}>
                                        {/* Provider accent dot */}
                                        <Box sx={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: providerColor, flexShrink: 0 }} />

                                        {/* Main info */}
                                        <Box
                                            sx={{ flex: 1, minWidth: 0, cursor: isSlskd ? 'pointer' : 'default' }}
                                            onClick={isSlskd ? () => setExpandedChoiceKey(isExpanded ? null : choiceKey) : undefined}
                                        >
                                            <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.75, mb: 0.25 }}>
                                                <Typography variant="body2" fontWeight={600} noWrap sx={{ flex: '0 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                                    {choice.title}
                                                </Typography>
                                                <Typography variant="caption" color="text.disabled" sx={{ flexShrink: 0 }}>
                                                    {choice.provider}
                                                </Typography>
                                            </Box>
                                            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
                                                <Typography variant="caption" sx={{ color: trackColor }}>
                                                    {resultTrackCount ?? '?'}/{expectedTrackCount ?? '?'}
                                                </Typography>
                                                {container !== '-' && (
                                                    <Box
                                                        component="span"
                                                        sx={{
                                                            fontSize: '0.58rem',
                                                            fontWeight: 700,
                                                            px: 0.5,
                                                            py: 0.1,
                                                            borderRadius: 0.5,
                                                            lineHeight: 1.5,
                                                            flexShrink: 0,
                                                            backgroundColor:
                                                                container === 'FLAC' ? 'info.main' :
                                                                container === 'MP3'  ? 'warning.main' :
                                                                'action.selected',
                                                            color:
                                                                container === 'FLAC' ? 'info.contrastText' :
                                                                container === 'MP3'  ? 'warning.contrastText' :
                                                                'text.secondary',
                                                        }}
                                                    >
                                                        {qualityLabel}
                                                    </Box>
                                                )}
                                                {isSlskd && uploadSpeed !== null && (
                                                    <Typography variant="caption" sx={{ color: speedColor }}>
                                                        {(uploadSpeed / 1_000_000).toFixed(1)} MB/s
                                                    </Typography>
                                                )}
                                                {isSlskd && queueLength !== null && (
                                                    <Typography variant="caption" sx={{ color: queueColor }}>
                                                        Q:{queueLength}
                                                    </Typography>
                                                )}
                                            </Box>
                                        </Box>

                                        {/* Score + actions */}
                                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flexShrink: 0 }}>
                                            <Typography variant="caption" sx={{
                                                fontSize: '0.65rem',
                                                fontWeight: 600,
                                                minWidth: 28,
                                                textAlign: 'right',
                                                color: choice.score > 0.9 ? 'success.main' : choice.score > 0.6 ? 'warning.main' : 'error.main',
                                            }}>
                                                {choice.score.toFixed(2)}
                                            </Typography>
                                            {isSlskd && (
                                                <IconButton size="small" onClick={() => setExpandedChoiceKey(isExpanded ? null : choiceKey)} sx={{ p: 0.25 }}>
                                                    {isExpanded ? <ChevronDownIcon size={14} /> : <ChevronRightIcon size={14} />}
                                                </IconButton>
                                            )}
                                            <IconButton
                                                onClick={() => mutation.mutate(choice)}
                                                disabled={mutation.isPending}
                                                color="primary"
                                                sx={{ p: 0.75 }}
                                            >
                                                {mutation.isPending ? <CircularProgress size={18} /> : <DownloadIcon size={18} />}
                                            </IconButton>
                                        </Box>
                                    </Box>

                                    {/* slskd expanded: 2-column tracklist */}
                                    {isExpanded && (
                                        <Box sx={{ borderTop: 1, borderColor: 'divider' }}>
                                            {/* Fixed column headers — outside scroll area */}
                                            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', borderBottom: 1, borderColor: 'divider', px: 1.5, py: 0.5, backgroundColor: 'action.hover' }}>
                                                <Typography variant="caption" fontWeight={700} color="text.disabled" sx={{ textTransform: 'uppercase', letterSpacing: '0.05em', fontSize: '0.6rem' }}>
                                                    Expected · {expectedTracks.length || expectedTrackCount || '?'}
                                                </Typography>
                                                <Typography variant="caption" fontWeight={700} color="text.disabled" sx={{ textTransform: 'uppercase', letterSpacing: '0.05em', fontSize: '0.6rem' }}>
                                                    Soulseek · {slskdAudioFiles.length}
                                                </Typography>
                                            </Box>
                                            {/* Scrollable track rows */}
                                            <Box sx={{ overflowY: 'auto', maxHeight: 220 }}>
                                            <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr' }}>
                                            <Box sx={{ borderRight: 1, borderColor: 'divider', px: 1.5, py: 0.75 }}>
                                                {expectedTracks.length > 0 ? expectedTracks.map((t: { title: string; track_position?: number }, ti: number) => (
                                                    <Box key={ti} sx={{ display: 'flex', gap: 0.75, lineHeight: 1.8 }}>
                                                        <Typography variant="caption" color="text.disabled" sx={{ flexShrink: 0, minWidth: 18, textAlign: 'right' }}>
                                                            {(t.track_position ?? ti + 1)}
                                                        </Typography>
                                                        <Typography variant="caption" noWrap>{t.title}</Typography>
                                                    </Box>
                                                )) : (
                                                    <Typography variant="caption" color="text.disabled">No data</Typography>
                                                )}
                                            </Box>
                                            <Box sx={{ px: 1.5, py: 0.75 }}>
                                                {/* placeholder — content below */}
                                                {slskdAudioFiles.map((f, fi) => {
                                                    const fname = String(f.filename ?? '');
                                                    const base = fname.replace(/\\/g, '/').split('/').pop() ?? fname;
                                                    const nameClean = base.replace(/\.[^.]+$/, '').replace(/^\d{1,3}[\s.\-_]+/, '');
                                                    return (
                                                        <Box key={fi} sx={{ display: 'flex', gap: 0.75, lineHeight: 1.8 }}>
                                                            <Typography variant="caption" color="text.disabled" sx={{ flexShrink: 0, minWidth: 18, textAlign: 'right' }}>
                                                                {fi + 1}
                                                            </Typography>
                                                            <Typography variant="caption" noWrap>{nameClean}</Typography>
                                                        </Box>
                                                    );
                                                })}
                                            </Box>
                                            </Box>
                                        </Box>
                                        </Box>
                                    )}
                                </Box>
                                    );
                                })()
                            ))}
                        </MuiList>
                        </>
                    ) : suggestionError ? (
                        <Alert severity="error" variant="outlined">
                            {suggestionError || 'Could not load download results'}
                        </Alert>
                    ) : (
                        <Alert severity="warning" variant="outlined">
                            No result found in deemix, squidwtf, or slskd.
                        </Alert>
                    )}
                </DialogContent>
                <DialogActions>
                    <Button onClick={closeDialog}>Close</Button>
                </DialogActions>
            </Dialog>
        </Box>
    );
}

function MissingAlbumsViewer({
    albums,
    artist,
    isRefreshing,
    onRefresh,
}: {
    albums: MissingAlbum[];
    artist: string;
    isRefreshing: boolean;
    onRefresh: () => Promise<void>;
}) {
    const [expandedId, setExpandedId] = useState<string | null>(null);
    const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
    const [batchProviders, setBatchProviders] = useState<Set<'deemix' | 'slskd' | 'squidwtf'>>(
        new Set(['deemix', 'slskd', 'squidwtf'])
    );
    const [batchQualities, setBatchQualities] = useState<Set<DownloadQuality>>(
        new Set(['flac', '320', '128'])
    );

    const albumEntries = useMemo(() => {
        return albums.map((album, idx) => ({
            id: album.mb_releasegroupid || `${album.album}-${album.year ?? 'na'}-${idx}`,
            album,
        }));
    }, [albums]);

    const grouped = useMemo(() => {
        const map = new Map<string, Array<{ id: string; album: MissingAlbum }>>();
        for (const entry of albumEntries) {
            const type = entry.album.release_type ?? 'album';
            if (!map.has(type)) map.set(type, []);
            map.get(type)!.push(entry);
        }
        return map;
    }, [albumEntries]);

    const selectedEntries = useMemo(
        () => albumEntries.filter((entry) => selectedIds.has(entry.id)),
        [albumEntries, selectedIds]
    );

    const allSelected = selectedIds.size > 0 && selectedIds.size === albumEntries.length;

    const batchMutation = useMutation({
        mutationFn: async () => {
            const payload = selectedEntries.map((entry) => {
                const releaseId = entry.album.mb_releasegroupid;
                const deezerId = releaseId?.startsWith('deezer:')
                    ? releaseId.slice(7)
                    : undefined;
                const squidAlbumId = releaseId?.startsWith('squid:')
                    ? releaseId.slice(6)
                    : undefined;

                return {
                    album: entry.album.album,
                    artist,
                    release_id: !deezerId ? (releaseId ?? undefined) : undefined,
                    deezer_id: deezerId,
                    squid_album_id: squidAlbumId,
                };
            });

            return startBatchDownload({
                providers: Array.from(batchProviders),
                qualities: Array.from(batchQualities),
                albums: payload,
            });
        },
        onSuccess: () => {
            setSelectedIds(new Set());
        },
    });

    if (albums.length === 0) {
        return (
            <Box
                sx={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 1,
                    height: '100%',
                }}
            >
                <Typography variant="body1" color="text.secondary">
                    No missing albums found.
                </Typography>
                <Tooltip title="Recompute from MusicBrainz & Deezer (bypass cache)">
                    <IconButton size="small" onClick={() => void onRefresh()} disabled={isRefreshing}>
                        {isRefreshing ? <CircularProgress size={16} /> : <RefreshCw size={16} />}
                    </IconButton>
                </Tooltip>
            </Box>
        );
    }

    const orderedTypes = [
        ...RELEASE_TYPE_ORDER.filter((t) => grouped.has(t)),
        ...[...grouped.keys()].filter((t) => !RELEASE_TYPE_ORDER.includes(t)),
    ];

    const toggleAll = () => {
        if (allSelected) {
            setSelectedIds(new Set());
            return;
        }
        setSelectedIds(new Set(albumEntries.map((entry) => entry.id)));
    };

    return (
        <Box sx={{ overflow: 'auto', height: '100%', display: 'flex', flexDirection: 'column' }}>
            <Box
                sx={{
                    display: 'grid',
                    gridTemplateColumns: 'auto 1fr',
                    gap: 2,
                    alignItems: 'stretch',
                    px: 1.25,
                    py: 1.25,
                    mb: 1,
                    border: 1,
                    borderColor: 'divider',
                    borderRadius: 1,
                    backgroundColor: 'grey.900',
                }}
            >
                <Box
                    sx={{
                        pr: 2,
                        borderRight: 1,
                        borderColor: 'divider',
                        display: 'flex',
                        flexDirection: 'column',
                        justifyContent: 'center',
                        gap: 0.5,
                    }}
                >
                    <Button
                        variant="contained"
                        color="primary"
                        disableElevation
                        size="small"
                        disabled={
                            selectedIds.size === 0 ||
                            batchMutation.isPending ||
                            batchProviders.size === 0 ||
                            batchQualities.size === 0
                        }
                        onClick={() => batchMutation.mutate()}
                        sx={{
                            minWidth: 190,
                            height: 36,
                            fontWeight: 700,
                            letterSpacing: 0.2,
                            textTransform: 'none',
                        }}
                    >
                        {batchMutation.isPending
                            ? 'Scheduling...'
                            : `Batch Download (${selectedIds.size})`}
                    </Button>
                    <FormControlLabel
                        sx={{ m: 0 }}
                        control={
                            <Checkbox
                                size="small"
                                checked={allSelected}
                                indeterminate={selectedIds.size > 0 && !allSelected}
                                onChange={toggleAll}
                            />
                        }
                        label={<Typography variant="caption" sx={{ fontWeight: 600 }}>Select all</Typography>}
                    />
                </Box>
                <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, alignItems: 'start' }}>
                    <FormControl component="fieldset" size="small">
                        <Typography variant="caption" sx={{ fontWeight: 700, mb: 0.75, display: 'block' }}>
                            Providers
                        </Typography>
                        <Typography variant="caption" sx={{ fontSize: '0.7rem', opacity: 0.8 }}>
                            Manual downloads are not affected by providers selection
                        </Typography>
                        <FormGroup row sx={{ gap: 0.5, alignItems: 'center' }}>
                        {(['deemix', 'slskd', 'squidwtf'] as const).map((provider) => (
                            <FormControlLabel
                                key={provider}
                                sx={{ mr: 1.5, ml: 0, alignItems: 'center' }}
                                control={
                                    <Checkbox
                                        size="small"
                                        checked={batchProviders.has(provider)}
                                        onChange={(e) => {
                                            setBatchProviders((prev) => {
                                                const next = new Set(prev);
                                                if (e.target.checked) {
                                                    next.add(provider);
                                                } else {
                                                    next.delete(provider);
                                                }
                                                return next;
                                            });
                                        }}
                                    />
                                }
                                label={<Typography variant="caption" sx={{ textTransform: 'lowercase' }}>{provider}</Typography>}
                            />
                        ))}
                        </FormGroup>
                    </FormControl>
                    <FormControl component="fieldset" size="small">
                        <Typography variant="caption" sx={{ fontWeight: 700, mb: 0.75, display: 'block' }}>
                            Qualities
                        </Typography>
                        <Typography variant="caption" sx={{ fontSize: '0.7rem', opacity: 0.8 }}>
                                The best quality will be selected for each album based on availability
                        </Typography>
                        <FormGroup row sx={{ gap: 0.5, alignItems: 'center' }}>
                        {(['flac', '320', '128'] as const).map((quality) => (
                            <FormControlLabel
                                key={quality}
                                sx={{ mr: 1.5, ml: 0, alignItems: 'center' }}
                                control={
                                    <Checkbox
                                        size="small"
                                        checked={batchQualities.has(quality)}
                                        onChange={(e) => {
                                            setBatchQualities((prev) => {
                                                const next = new Set(prev);
                                                if (e.target.checked) {
                                                    next.add(quality);
                                                } else {
                                                    next.delete(quality);
                                                }
                                                return next;
                                            });
                                        }}
                                    />
                                }
                                label={
                                    <Typography variant="caption">
                                        {quality === 'flac' ? 'FLAC' : `MP3 ${quality}`}
                                    </Typography>
                                }
                            />
                        ))}
                        </FormGroup>
                    </FormControl>
                </Box>
                {batchMutation.isError && (
                    <Typography variant="caption" color="error.main">
                        {(batchMutation.error as Error)?.message ?? 'Batch scheduling failed'}
                    </Typography>
                )}
                {batchMutation.data && (
                    <Typography variant="caption" color="text.secondary">
                        Queued {batchMutation.data.queued}/{batchMutation.data.requested}
                    </Typography>
                )}
            </Box>
            {orderedTypes.map((type) => (
                <Box key={type} sx={{ mb: 3 }}>
                    {(() => {
                        const typeEntries = grouped.get(type) ?? [];
                        const typeSelected = typeEntries.filter((e) => selectedIds.has(e.id)).length;
                        const allTypeSelected = typeEntries.length > 0 && typeSelected === typeEntries.length;
                        const typeIndeterminate = typeSelected > 0 && !allTypeSelected;

                        return (
                            <Box
                                sx={{
                                    px: 1,
                                    py: 0.25,
                                    position: 'sticky',
                                    top: 0,
                                    zIndex: 1,
                                    backgroundColor: 'background.paper',
                                    borderBottom: 1,
                                    borderColor: 'divider',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 1,
                                }}
                            >
                                <Tooltip title={allTypeSelected ? 'Unselect this type' : 'Select this type'}>
                                    <Checkbox
                                        size="small"
                                        checked={allTypeSelected}
                                        indeterminate={typeIndeterminate}
                                        onChange={() => {
                                            setSelectedIds((prev) => {
                                                const next = new Set(prev);
                                                if (allTypeSelected) {
                                                    typeEntries.forEach((e) => next.delete(e.id));
                                                } else {
                                                    typeEntries.forEach((e) => next.add(e.id));
                                                }
                                                return next;
                                            });
                                        }}
                                    />
                                </Tooltip>
                                <Typography variant="subtitle2" color="text.secondary">
                                    {RELEASE_TYPE_LABELS[type] ?? type} ({typeEntries.length})
                                </Typography>
                            </Box>
                        );
                    })()}
                    <Table size="small" sx={{ tableLayout: 'fixed', width: '100%' }}>
                        <TableHead>
                            <TableRow sx={{ '& .MuiTableCell-root': { py: 0.5, borderBottom: 1, borderColor: 'divider', color: 'text.disabled', fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.04em' } }}>
                                <TableCell sx={{ width: 40 }} />
                                <TableCell sx={{ width: 40 }} />
                                <TableCell sx={{ pl: 1 }}>Album</TableCell>
                                <TableCell sx={{ width: 68 }} />
                                <TableCell sx={{ width: 92, textAlign: 'center' }}>Download</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {grouped.get(type)!.map((entry) => {
                                const rowId = entry.id;
                                const album = entry.album;
                                const isExpanded = expandedId === rowId;
                                const isSelected = selectedIds.has(rowId);
                                const isMbEntry = Boolean(
                                    album.mb_releasegroupid &&
                                    !album.mb_releasegroupid.startsWith('deezer:')
                                );
                                const deezerIdStr = album.deezer_id
                                    ? String(album.deezer_id)
                                    : album.mb_releasegroupid?.startsWith('deezer:')
                                      ? album.mb_releasegroupid.slice(7)
                                      : null;
                                const mbUrl = isMbEntry
                                    ? `https://musicbrainz.org/release-group/${album.mb_releasegroupid}`
                                    : null;
                                const deezerUrl = deezerIdStr
                                    ? `https://www.deezer.com/album/${deezerIdStr}`
                                    : null;
                                return (
                                    <>
                                        <TableRow
                                            key={`${rowId}-row`}
                                            hover
                                            sx={{ cursor: album.mb_releasegroupid ? 'pointer' : 'default' }}
                                            onClick={() => {
                                                if (!album.mb_releasegroupid) return;
                                                setExpandedId(isExpanded ? null : rowId);
                                            }}
                                        >
                                            {/* Checkbox */}
                                            <TableCell sx={{ p: 0.5, width: 40 }} onClick={(e: { stopPropagation: () => void }) => e.stopPropagation()}>
                                                <Checkbox
                                                    size="small"
                                                    checked={isSelected}
                                                    onChange={() => {
                                                        setSelectedIds((prev) => {
                                                            const next = new Set(prev);
                                                            if (next.has(rowId)) next.delete(rowId);
                                                            else next.add(rowId);
                                                            return next;
                                                        });
                                                    }}
                                                />
                                            </TableCell>

                                            {/* Cover */}
                                            <TableCell sx={{ p: 0.5, width: 40 }}>
                                                {album.cover_url ? (
                                                    <Box component="img" src={album.cover_url} alt={album.album}
                                                        sx={{ width: 32, height: 32, objectFit: 'cover', borderRadius: 0.5, display: 'block' }}
                                                        loading="lazy"
                                                    />
                                                ) : (
                                                    <Box sx={{ width: 32, height: 32, borderRadius: 0.5, backgroundColor: 'action.hover', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                                        <AlbumIcon size={16} />
                                                    </Box>
                                                )}
                                            </TableCell>

                                            {/* Album name + year/tracks inline */}
                                            <TableCell sx={{ pl: 1, py: 0.75 }}>
                                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.2 }}>
                                                    {album.mb_releasegroupid && (
                                                        isExpanded ? <ChevronDownIcon size={12} /> : <ChevronRightIcon size={12} />
                                                    )}
                                                    <Typography variant="body2" fontWeight={600} sx={{ lineHeight: 1.3 }}>
                                                        {album.album}
                                                    </Typography>
                                                </Box>
                                                <Box sx={{ display: 'flex', gap: 0.75, alignItems: 'center', pl: album.mb_releasegroupid ? 2.5 : 0 }}>
                                                    <Typography variant="caption" color="text.disabled" component="span">
                                                        <MissingAlbumTrackCount album={album} /> tracks
                                                    </Typography>
                                                    {album.year && (
                                                        <Typography variant="caption" color="text.disabled">· {album.year}</Typography>
                                                    )}
                                                </Box>
                                            </TableCell>

                                            {/* External links with brand icons */}
                                            <TableCell sx={{ p: 0.5, width: 68 }} onClick={(e: { stopPropagation: () => void }) => e.stopPropagation()}>
                                                <Box sx={{ display: 'flex', gap: 0.25 }}>
                                                    {mbUrl && (
                                                        <Tooltip title="Open on MusicBrainz">
                                                            <IconButton size="small" component="a" href={mbUrl} target="_blank" rel="noopener noreferrer" sx={{ p: 0.5 }}>
                                                                <svg role="img" viewBox="0 0 24 24" width={16} height={16} xmlns="http://www.w3.org/2000/svg" fill="currentColor">
                                                                    <path d="M11.582 0L1.418 5.832v12.336L11.582 24V10.01L7.1 12.668v3.664c.01.111.01.225 0 .336-.103.435-.54.804-1 1.111-.802.537-1.752.509-2.166-.111-.413-.62-.141-1.631.666-2.168.384-.28.863-.399 1.334-.332V6.619c0-.154.134-.252.226-.308L11.582 3zm.836 0v6.162c.574.03 1.14.16 1.668.387a2.225 2.225 0 0 0 1.656-.717 1.02 1.02 0 1 1 1.832-.803l.004.006a1.022 1.022 0 0 1-1.295 1.197c-.34.403-.792.698-1.297.85.34.263.641.576.891.928a1.04 1.04 0 0 1 .777.125c.768.486.568 1.657-.318 1.857-.886.2-1.574-.77-1.09-1.539.02-.03.042-.06.065-.09a3.598 3.598 0 0 0-1.436-1.166 4.142 4.142 0 0 0-1.457-.369v4.01c.855.06 1.256.493 1.555.834.227.256.356.39.578.402.323.018.568.008.806 0a5.44 5.44 0 0 1 .895.022c.94-.017 1.272-.226 1.605-.446a2.533 2.533 0 0 1 1.131-.463 1.027 1.027 0 0 1 .12-.263 1.04 1.04 0 0 1 .105-.137c.023-.025.047-.044.07-.066a4.775 4.775 0 0 1 0-2.405l-.012-.01a1.02 1.02 0 1 1 .692.272h-.057a4.288 4.288 0 0 0 0 1.877h.063a1.02 1.02 0 1 1-.545 1.883l-.047-.033a1 1 0 0 1-.352-.442 1.885 1.885 0 0 0-.814.354 3.03 3.03 0 0 1-.703.365c.757.555 1.772 1.6 2.199 2.299a1.03 1.03 0 0 1 .256-.033 1.02 1.02 0 1 1-.545 1.88l-.047-.03a1.017 1.017 0 0 1-.27-1.376.72.72 0 0 1 .051-.072c-.445-.775-2.026-2.28-2.46-2.387a4.037 4.037 0 0 0-1.31-.117c-.24.008-.513.018-.866 0-.515-.027-.783-.333-1.043-.629-.26-.296-.51-.56-1.055-.611V18.5a1.877 1.877 0 0 0 .426-.135.333.333 0 0 1 .058-.027c.56-.267 1.421-.91 2.096-2.447a1.02 1.02 0 0 1-.27-1.344 1.02 1.02 0 1 1 .915 1.54 6.273 6.273 0 0 1-1.432 2.136 1.785 1.785 0 0 1 .691.306.667.667 0 0 0 .37.168 3.31 3.31 0 0 0 .888-.222 1.02 1.02 0 0 1 1.787-.79v-.005a1.02 1.02 0 0 1-.773 1.683 1.022 1.022 0 0 1-.719-.287 3.935 3.935 0 0 1-1.168.287h-.05a1.313 1.313 0 0 1-.71-.275c-.262-.177-.51-.345-1.402-.12a2.098 2.098 0 0 1-.707.2V24l10.164-5.832V5.832zm4.154 4.904a.352.352 0 0 0-.197.639l.018.01c.163.1.378.053.484-.108v-.002a.352.352 0 0 0-.303-.539zm-4.99 1.928L7.082 9.5v2l4.5-2.668zm8.385.38a.352.352 0 0 0-.295.165v.002a.35.35 0 0 0 .096.473l.013.01a.357.357 0 0 0 .487-.108.352.352 0 0 0-.301-.541zM16.09 8.647a.352.352 0 0 0-.277.163.355.355 0 0 0 .296.54c.482 0 .463-.73-.02-.703zm3.877 2.477a.352.352 0 0 0-.295.164.35.35 0 0 0 .094.475l.015.01a.357.357 0 0 0 .485-.11.352.352 0 0 0-.3-.539zm-4.375 3.594a.352.352 0 0 0-.291.172.35.35 0 0 0-.04.265.352.352 0 1 0 .33-.437zm4.375.789a.352.352 0 0 0-.295.164v.002a.352.352 0 0 0 .094.473l.015.01a.357.357 0 0 0 .485-.108.352.352 0 0 0-.3-.54zm-2.803 2.488v.002a.347.347 0 0 0-.223.084.352.352 0 0 0 .23.62.347.347 0 0 0 .23-.085.348.348 0 0 0 .12-.24.353.353 0 0 0-.35-.38.347.347 0 0 0-.007 0Z"/>
                                                                </svg>
                                                            </IconButton>
                                                        </Tooltip>
                                                    )}
                                                    {deezerUrl && (
                                                        <Tooltip title="Open on Deezer">
                                                            <IconButton size="small" component="a" href={deezerUrl} target="_blank" rel="noopener noreferrer" sx={{ p: 0.5 }}>
                                                                <svg role="img" viewBox="0 0 24 24" width={16} height={16} xmlns="http://www.w3.org/2000/svg" fill="currentColor">
                                                                    <path d="M.693 10.024c.381 0 .693-1.256.693-2.807 0-1.55-.312-2.807-.693-2.807C.312 4.41 0 5.666 0 7.217s.312 2.808.693 2.808ZM21.038 1.56c-.364 0-.684.805-.91 2.096C19.765 1.446 19.184 0 18.526 0c-.78 0-1.464 2.036-1.784 5-.312-2.158-.788-3.536-1.325-3.536-.745 0-1.386 2.704-1.62 6.472-.442-1.932-1.083-3.145-1.793-3.145s-1.35 1.213-1.793 3.145c-.242-3.76-.874-6.463-1.628-6.463-.537 0-1.013 1.378-1.325 3.535C6.938 2.036 6.262 0 5.474 0c-.658 0-1.247 1.447-1.602 3.665-.217-1.291-.546-2.105-.91-2.105-.675 0-1.221 2.807-1.221 6.272 0 3.466.546 6.273 1.221 6.273.277 0 .537-.476.736-1.273.32 2.928.996 4.938 1.776 4.938.606 0 1.143-1.204 1.507-3.11.251 3.622.875 6.195 1.602 6.195.46 0 .875-1.023 1.187-2.677C10.142 21.6 11 24 12.004 24c1.005 0 1.863-2.4 2.235-5.822.312 1.654.727 2.677 1.186 2.677.728 0 1.352-2.573 1.603-6.195.364 1.906.9 3.11 1.507 3.11.78 0 1.455-2.01 1.775-4.938.208.797.46 1.273.737 1.273.675 0 1.22-2.807 1.22-6.273-.008-3.457-.553-6.272-1.23-6.272ZM23.307 10.024c.381 0 .693-1.256.693-2.807 0-1.55-.312-2.807-.693-2.807-.381 0-.693 1.256-.693 2.807s.312 2.808.693 2.808Z"/>
                                                                </svg>
                                                            </IconButton>
                                                        </Tooltip>
                                                    )}
                                                </Box>
                                            </TableCell>

                                            {/* Download */}
                                            <TableCell sx={{ p: 0.5, width: 92, textAlign: 'center' }} onClick={(e) => e.stopPropagation()}>
                                                <DownloadButton album={album} artist={artist} />
                                            </TableCell>
                                        </TableRow>
                                        {isExpanded && album.mb_releasegroupid && (
                                            <TableRow key={`${rowId}-tracks`}>
                                                <TableCell colSpan={5} sx={{ p: 0, borderBottom: 'none' }}>
                                                    <Collapse in={isExpanded} unmountOnExit>
                                                        <TrackList releaseId={album.mb_releasegroupid} />
                                                    </Collapse>
                                                </TableCell>
                                            </TableRow>
                                        )}
                                    </>
                                );
                            })}
                        </TableBody>
                    </Table>
                </Box>
            ))}
        </Box>
    );
}
