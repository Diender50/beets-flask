import { useMemo, useState } from 'react';
import { List } from 'react-window';
import {
    Badge,
    Box,
    BoxProps,
    Chip,
    CircularProgress,
    Collapse,
    Divider,
    IconButton,
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
import { ChevronDownIcon, ChevronRightIcon, ExternalLinkIcon } from 'lucide-react';
import { useQuery, useSuspenseQuery } from '@tanstack/react-query';
import { createFileRoute, Link } from '@tanstack/react-router';

import {
    Album,
    albumsByArtistQueryOptions,
    artistQueryOptions,
    Item,
    itemsByArtistQueryOptions,
    MissingAlbum,
    missingAlbumsByArtistQueryOptions,
    missingAlbumTracksQueryOptions,
} from '@/api/library';
import {
    AlbumGridCell,
    AlbumListRow,
} from '@/components/common/browser/albums';
import { ItemListRow } from '@/components/common/browser/items';
import { AlbumIcon, ArtistIcon, TrackIcon } from '@/components/common/icons';
import { Search } from '@/components/common/inputs/search';
import { DynamicFlowGrid, ViewToggle } from '@/components/common/table';

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
        const p4 = opts.context.queryClient.ensureQueryData(
            missingAlbumsByArtistQueryOptions(opts.params.artist)
        );
        await Promise.all([p1, p2, p3, p4]);
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
    const { data: missingAlbums } = useSuspenseQuery(
        missingAlbumsByArtistQueryOptions(params.artist)
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
                missingAlbums={missingAlbums}
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
    missingAlbums,
    sx,
    ...props
}: {
    albums: Album<false, true>[];
    items: Item<true>[];
    missingAlbums: MissingAlbum[];
} & BoxProps) {
    const theme = useTheme();
    const [selected, setSelected] = useState<'albums' | 'items' | 'missing'>(() =>
        albums.length > 0 ? 'albums' : 'items'
    );
    const [view, setView] = useState<'list' | 'grid'>('list');
    const [filter, setFilter] = useState('');
    const [albumTypeFilter, setAlbumTypeFilter] = useState<string | null>(null);

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

    const filteredItems = useMemo(() => {
        if (!filter) {
            return items;
        }
        return items.filter((item) => {
            return item.name.toLowerCase().includes(filter.toLowerCase());
        });
    }, [items, filter]);

    const filteredMissingAlbums = useMemo(() => {
        if (!filter) {
            return missingAlbums;
        }
        return missingAlbums.filter((album) => {
            return album.album.toLowerCase().includes(filter.toLowerCase());
        });
    }, [missingAlbums, filter]);

    const nAlbumsRemovedByFilter = albums.length - filteredAlbums.length;
    const nItemsRemovedByFilter = items.length - filteredItems.length;
    const nMissingRemovedByFilter =
        missingAlbums.length - filteredMissingAlbums.length;

    const nRemovedByFilter =
        selected === 'albums'
            ? nAlbumsRemovedByFilter
            : selected === 'items'
              ? nItemsRemovedByFilter
              : nMissingRemovedByFilter;

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
                                v: 'albums' | 'items' | 'missing' | null
                            ) => {
                                if (v) setSelected(v);
                            }}
                            color="primary"
                            exclusive
                            aria-label="Filter type"
                        >
                            <ToggleButton value="items">
                                <TrackIcon size={theme.iconSize.lg} />
                            </ToggleButton>
                            <ToggleButton value="albums">
                                <AlbumIcon size={theme.iconSize.lg} />
                            </ToggleButton>
                            <ToggleButton value="missing">
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
                            </ToggleButton>
                        </ToggleButtonGroup>
                        <ViewToggle
                            view={view}
                            setView={setView}
                            sx={{ marginLeft: 'auto' }}
                        />
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
                {selected === 'items' && <ItemsViewer items={filteredItems} />}
                {selected === 'albums' && (
                    <AlbumsViewer albums={filteredAlbums} view={view} />
                )}
                {selected === 'missing' && (
                    <MissingAlbumsViewer albums={filteredMissingAlbums} />
                )}
            </Box>
        </Box>
    );
}

function AlbumsViewer({
    albums,
    view,
}: {
    albums: Album<false, true>[];
    view: 'list' | 'grid';
}) {
    if (albums.length === 0) {
        return (
            <Box
                sx={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    height: '100%',
                }}
            >
                <Typography variant="body1" color="text.secondary">
                    No albums found.
                </Typography>
            </Box>
        );
    }

    if (view === 'grid') {
        return (
            <DynamicFlowGrid
                cellProps={{ albums: albums }}
                cellCount={albums.length}
                cellHeight={150}
                cellWidth={150}
                cellComponent={AlbumGridCell}
            />
        );
    }
    return (
        <List
            rowProps={{ albums, showArtist: false }}
            rowCount={albums.length}
            rowHeight={35}
            rowComponent={AlbumListRow}
        />
    );
}

function ItemsViewer({ items }: { items: Item<true>[] }) {
    if (items.length === 0) {
        return (
            <Box
                sx={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    height: '100%',
                }}
            >
                <Typography variant="body1" color="text.secondary">
                    No items found.
                </Typography>
            </Box>
        );
    }

    return (
        <List
            rowProps={{ items, showArtist: false }}
            rowCount={items.length}
            rowHeight={50}
            overscanCount={50}
            rowComponent={ItemListRow}
        />
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

function MissingAlbumsViewer({ albums }: { albums: MissingAlbum[] }) {
    const [expandedId, setExpandedId] = useState<string | null>(null);

    if (albums.length === 0) {
        return (
            <Box
                sx={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    height: '100%',
                }}
            >
                <Typography variant="body1" color="text.secondary">
                    No missing albums found.
                </Typography>
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
