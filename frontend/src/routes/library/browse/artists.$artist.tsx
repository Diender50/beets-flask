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
    Collapse,
    Divider,
    IconButton,
    List as MuiList,
    ListItemButton,
    ListItemText,
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
import { CheckIcon, ChevronDownIcon, ChevronRightIcon, DownloadIcon, ExternalLinkIcon, RefreshCw, XCircleIcon } from 'lucide-react';
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
    DownloadSuggestion,
    getDownloadJob,
    getDownloadSuggestions,
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
    const [selected, setSelected] = useState<'albums' | 'missing'>('albums');
    const [filter, setFilter] = useState('');
    const [albumTypeFilter, setAlbumTypeFilter] = useState<string | null>(null);

    const missingAlbumsQuery = useQuery({
        ...missingAlbumsByArtistQueryOptions(artist),
        enabled: selected === 'missing',
    });
    const missingAlbums = missingAlbumsQuery.data ?? [];

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
                            gap: 2,
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
                        <MissingAlbumsViewer albums={filteredMissingAlbums} artist={artist} />
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
    const expectedTrackCount = useExpectedTrackCount(album);
    const [jobId, setJobId] = useState<string | null>(null);
    const [open, setOpen] = useState(false);
    const [searchCycle, setSearchCycle] = useState(0);
    const [suggestionChoices, setSuggestionChoices] = useState<DownloadSuggestion[]>([]);
    const [slskdLoading, setSlskdLoading] = useState(false);
    const [deemixLoading, setDeemixLoading] = useState(false);
    const [squidwtfLoading, setSquidwtfLoading] = useState(false);
    const [suggestionErrors, setSuggestionErrors] = useState<string[]>([]);
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
                });
                mergeChoices(data.results ?? []);
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

    const suggestionLoading = slskdLoading || deemixLoading || squidwtfLoading;
    const suggestionError = suggestionErrors.join(' | ');

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
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0.25 }}>
            <Tooltip title={tooltipTitle}>
                <span>
                    <IconButton
                        size="small"
                        onClick={openDialog}
                        disabled={mutation.isPending || status === 'pending' || status === 'downloading'}
                        color={iconColor}
                    >
                        {mutation.isPending || status === 'pending' || status === 'downloading' ? (
                            <CircularProgress size={14} />
                        ) : status === 'done' ? (
                            <CheckIcon size={16} />
                        ) : status === 'error' ? (
                            <XCircleIcon size={16} />
                        ) : (
                            <DownloadIcon size={16} />
                        )}
                    </IconButton>
                </span>
            </Tooltip>
            <Typography
                variant="caption"
                sx={{ lineHeight: 1, textAlign: 'center', color: status === 'error' ? 'error.main' : 'text.secondary' }}
            >
                {statusText}
            </Typography>
            <Box sx={{ width: 220, mt: 0.5, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                {detailLines.length > 0 && (
                    <Alert
                        severity={status === 'error' ? 'error' : status === 'done' ? 'success' : 'info'}
                        variant="outlined"
                        sx={{ p: 0.5, '.MuiAlert-message': { py: 0, width: '100%' } }}
                    >
                        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
                            {detailLines.slice(0, 4).map((line) => (
                                <Typography key={line} variant="caption" sx={{ lineHeight: 1.2 }}>
                                    {line}
                                </Typography>
                            ))}
                        </Box>
                    </Alert>
                )}
                {status === 'error' && currentJob?.error && (
                    <Alert severity="error" variant="filled" sx={{ p: 0.5, '.MuiAlert-message': { py: 0, width: '100%' } }}>
                        <Typography variant="caption" sx={{ lineHeight: 1.2 }}>
                            {currentJob.error}
                        </Typography>
                    </Alert>
                )}
            </Box>
            <Dialog open={open} onClose={closeDialog} fullWidth maxWidth="md">
                <DialogTitle>Choose download result</DialogTitle>
                <DialogContent dividers>
                    {suggestionLoading && suggestionChoices.length === 0 ? (
                        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                            <CircularProgress size={24} />
                        </Box>
                    ) : suggestionChoices.length > 0 ? (
                        <>
                            {(deemixLoading || slskdLoading || squidwtfLoading) && (
                                <Alert severity="info" variant="outlined" sx={{ mb: 1 }}>
                                    Searching {[
                                        slskdLoading ? 'slskd' : null,
                                        deemixLoading ? 'deemix' : null,
                                        squidwtfLoading ? 'squidwtf' : null,
                                    ].filter(Boolean).join(', ')}...
                                </Alert>
                            )}
                        <MuiList disablePadding>
                            {suggestionChoices.map((choice, index) => (
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
                                    const trackColor = trackMatchColor(resultTrackCount, expectedTrackCount);
                                    const speedColor = speedMatchColor(uploadSpeed, queueLength, hasFreeUploadSlot);
                                    const queueColor = queueMatchColor(queueLength);
                                    return (
                                <ListItemButton
                                    key={`${choice.provider}-${choice.title}-${index}`}
                                    onClick={() => mutation.mutate(choice)}
                                    disabled={mutation.isPending}
                                    sx={{
                                        borderRadius: 1,
                                        mb: 1,
                                        border: 1,
                                        borderColor: 'divider',
                                        alignItems: 'flex-start',
                                    }}
                                >
                                    <ListItemText
                                        primary={
                                            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
                                                <Typography variant="body2" fontWeight={700}>
                                                    {choice.title}
                                                </Typography>
                                                <Chip
                                                    size="small"
                                                    label={choice.provider}
                                                    color={choice.provider === 'deemix' ? 'primary' : choice.provider === 'squidwtf' ? 'success' : 'secondary'}
                                                />
                                                <Chip size="small" label={`score ${choice.score.toFixed(3)}`} variant="outlined" />
                                            </Box>
                                        }
                                        secondary={
                                            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25, mt: 0.5 }}>
                                                <Typography variant="caption" color="text.secondary">
                                                    {choice.artist}
                                                </Typography>
                                                {choice.provider === 'deemix' ? (
                                                    <>
                                                        <Typography variant="caption" color="text.secondary">
                                                            Deezer ID: {String(choice.details.deezer_id ?? '-')}
                                                        </Typography>
                                                        <Typography variant="caption" sx={{ color: trackColor }}>
                                                            Tracks: {resultTrackCount ?? '-'} / {expectedTrackCount ?? '-'}
                                                            {container !== '-' ? ` • ${container}` : ''}
                                                            {kbps !== null ? ` • ${Math.round(kbps)} kbps` : ''}
                                                        </Typography>
                                                    </>
                                                ) : choice.provider === 'squidwtf' ? (
                                                    <>
                                                        <Typography variant="caption" color="text.secondary">
                                                            Squid album ID: {String(choice.details.squid_album_id ?? '-')}
                                                        </Typography>
                                                        <Typography variant="caption" sx={{ color: trackColor }}>
                                                            Tracks: {resultTrackCount ?? '-'} / {expectedTrackCount ?? '-'}
                                                            {container !== '-' ? ` • ${container}` : ''}
                                                            {kbps !== null ? ` • ${Math.round(kbps)} kbps` : ''}
                                                        </Typography>
                                                    </>
                                                ) : (
                                                    <>
                                                        <Typography variant="caption" color="text.secondary">
                                                            <Box component="span">
                                                                User: {String(choice.details.username ?? '-')}
                                                            </Box>
                                                            {' • '}
                                                            <Box component="span" sx={{ color: speedColor }}>
                                                                Speed: {uploadSpeed !== null ? `${(uploadSpeed / 1_000_000).toFixed(1)} MB/s` : '-'}
                                                            </Box>
                                                            {' • '}
                                                            <Box component="span" sx={{ color: queueColor }}>
                                                                Queue: {queueLength ?? '-'}
                                                            </Box>
                                                        </Typography>
                                                        <Typography variant="caption" sx={{ color: trackColor }}>
                                                            Tracks: {resultTrackCount ?? '-'} / {expectedTrackCount ?? '-'}
                                                            {container !== '-' ? ` • ${container}` : ''}
                                                            {kbps !== null ? ` • ${Math.round(kbps)} kbps` : ''}
                                                        </Typography>
                                                    </>
                                                )}
                                            </Box>
                                        }
                                    />
                                </ListItemButton>
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

function MissingAlbumsViewer({ albums, artist }: { albums: MissingAlbum[]; artist: string }) {
    const [expandedId, setExpandedId] = useState<string | null>(null);
    const queryClient = useQueryClient();
    const [refreshing, setRefreshing] = useState(false);

    const handleRefresh = async () => {
        console.log('[missing_albums] refresh click', { artist });
        setRefreshing(true);
        try {
            const fresh = await fetchMissingAlbumsByArtist(artist, true);
            queryClient.setQueryData(
                missingAlbumsByArtistQueryOptions(artist).queryKey,
                fresh
            );
            console.log('[missing_albums] refresh done', {
                artist,
                count: fresh.length,
            });
        } catch (error) {
            console.error('[missing_albums] refresh failed', { artist, error });
        } finally {
            setRefreshing(false);
        }
    };

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
                <Tooltip title="Refresh missing albums">
                    <IconButton size="small" onClick={() => void handleRefresh()} disabled={refreshing}>
                        {refreshing ? <CircularProgress size={16} /> : <RefreshCw size={16} />}
                    </IconButton>
                </Tooltip>
            </Box>
        );
    }

    const grouped = useMemo(() => {
        const map = new Map<string, MissingAlbum[]>();
        for (const album of albums) {
            const type = album.release_type ?? 'album';
            if (!map.has(type)) map.set(type, []);
            map.get(type)!.push(album);
        }
        return map;
    }, [albums]);

    const orderedTypes = [
        ...RELEASE_TYPE_ORDER.filter((t) => grouped.has(t)),
        ...[...grouped.keys()].filter((t) => !RELEASE_TYPE_ORDER.includes(t)),
    ];

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
                                <TableCell sx={{ width: 48 }} />
                                <TableCell sx={{ width: 48 }} />
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {grouped.get(type)!.map((album, idx) => {
                                const rowId = album.mb_releasegroupid || `${album.album}-${idx}`;
                                const isExpanded = expandedId === rowId;
                                const deezerId = album.mb_releasegroupid?.startsWith('deezer:')
                                    ? album.mb_releasegroupid.slice(7)
                                    : null;
                                const deezerUrl = deezerId
                                    ? `https://www.deezer.com/album/${deezerId}`
                                    : album.mb_releasegroupid
                                      ? `https://musicbrainz.org/release-group/${album.mb_releasegroupid}`
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
                                            <TableCell sx={{ p: 0.5, width: 44 }}>
                                                {album.cover_url ? (
                                                    <Box
                                                        component="img"
                                                        src={album.cover_url}
                                                        alt={album.album}
                                                        sx={{
                                                            width: 36,
                                                            height: 36,
                                                            objectFit: 'cover',
                                                            borderRadius: 0.5,
                                                            display: 'block',
                                                        }}
                                                        loading="lazy"
                                                    />
                                                ) : (
                                                    <Box
                                                        sx={{
                                                            width: 36,
                                                            height: 36,
                                                            borderRadius: 0.5,
                                                            backgroundColor: 'action.hover',
                                                            display: 'flex',
                                                            alignItems: 'center',
                                                            justifyContent: 'center',
                                                        }}
                                                    >
                                                        <AlbumIcon size={20} />
                                                    </Box>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                                    {album.mb_releasegroupid && (
                                                        isExpanded
                                                            ? <ChevronDownIcon size={14} />
                                                            : <ChevronRightIcon size={14} />
                                                    )}
                                                    {album.album}
                                                </Box>
                                            </TableCell>
                                            <TableCell align="right" sx={{ color: 'text.secondary' }}>
                                                <MissingAlbumTrackCount album={album} />
                                            </TableCell>
                                            <TableCell>{album.year ?? '-'}</TableCell>
                                            <TableCell sx={{ p: 0.5 }} onClick={(e) => e.stopPropagation()}>
                                                {deezerUrl && (
                                                    <Tooltip
                                                        title={
                                                            deezerId
                                                                ? 'Open on Deezer'
                                                                : 'Open on MusicBrainz'
                                                        }
                                                    >
                                                        <IconButton
                                                            size="small"
                                                            component="a"
                                                            href={deezerUrl}
                                                            target="_blank"
                                                            rel="noopener noreferrer"
                                                        >
                                                            <ExternalLinkIcon size={16} />
                                                        </IconButton>
                                                    </Tooltip>
                                                )}
                                            </TableCell>
                                            <TableCell sx={{ p: 0.5 }} onClick={(e) => e.stopPropagation()}>
                                                <DownloadButton album={album} artist={artist} />
                                            </TableCell>
                                        </TableRow>
                                        {isExpanded && album.mb_releasegroupid && (
                                            <TableRow key={`${rowId}-tracks`}>
                                                <TableCell colSpan={6} sx={{ p: 0, borderBottom: 'none' }}>
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
