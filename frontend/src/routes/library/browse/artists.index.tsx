import { useEffect, useMemo, useState } from 'react';
import {
    Box,
    BoxProps,
    Button,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogContentText,
    DialogTitle,
    FormControlLabel,
    IconButton,
    InputAdornment,
    List,
    ListItem,
    ListItemAvatar,
    ListItemText,
    Avatar,
    Switch,
    TextField,
    Tooltip,
    Typography,
} from '@mui/material';
import { UserRoundPlusIcon, SearchIcon, CheckIcon, RefreshCw, ExternalLinkIcon, Trash2Icon } from 'lucide-react';
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query';
import { createFileRoute } from '@tanstack/react-router';

import { Artist, artistsQueryOptions, fetchMissingAlbumsByArtist, missingAlbumsByArtistQueryOptions } from '@/api/library';
import {
    ArtistSearchResult,
    TrackedArtist,
    addTrackedArtist,
    trackedArtistsQueryOptions,
    searchArtists,
    removeTrackedArtist,
} from '@/api/discovery';
import { meQueryOptions } from '@/api/auth';
import { ArtistIcon } from '@/components/common/icons';
import { Search } from '@/components/common/inputs/search';
import { ArtistsTable } from '@/components/common/browser/artistsTable';

export const Route = createFileRoute('/library/browse/artists/')({
    loader: async (opts) => {
        await opts.context.queryClient.ensureQueryData(artistsQueryOptions());
    },
    component: RouteComponent,
});

function RouteComponent() {
    const { data: libraryArtists } = useSuspenseQuery(artistsQueryOptions());
    const { data: trackedArtists = [] } = useQuery(trackedArtistsQueryOptions());
    const { data: me } = useQuery(meQueryOptions());
    const canAddArtist = me?.can_add_artist ?? true;

    const [addDialogOpen, setAddDialogOpen] = useState(false);
    const [albumArtistOnly, setAlbumArtistOnly] = useState(true);

    const libraryNames = useMemo(
        () => new Set(libraryArtists.map((a) => a.artist.toLowerCase())),
        [libraryArtists]
    );

    const mergedArtists: Artist[] = useMemo(() => {
        const libraryWithState: Artist[] = libraryArtists.map((artist) => ({
            ...artist,
            in_library: true,
        }));

        const trackedOnly: Artist[] = trackedArtists
            .filter((f) => !libraryNames.has(f.name.toLowerCase()))
            .map((f) => ({
                artist: f.name,
                display_name: undefined,
                album_count: 0,
                item_count: 0,
                missing_count: f.missing_count ?? 0,
                total_size: 0,
                in_library: false,
            }));
        return [...libraryWithState, ...trackedOnly];
    }, [libraryArtists, trackedArtists, libraryNames]);

    const displayedArtists = useMemo(() => {
        if (!albumArtistOnly) return mergedArtists;
        return mergedArtists.filter((a) => (a.album_count ?? 0) > 0 || !a.in_library);
    }, [mergedArtists, albumArtistOnly]);

    return (
        <>
            <ArtistsListWrapper
                artists={displayedArtists}
                nArtists={displayedArtists.length}
                albumArtistOnly={albumArtistOnly}
                onAlbumArtistOnlyChange={setAlbumArtistOnly}
                onAddArtist={() => setAddDialogOpen(true)}
                canAddArtist={canAddArtist}
                sx={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}
            />
            <AddArtistDialog
                open={addDialogOpen}
                onClose={() => setAddDialogOpen(false)}
                trackedArtists={trackedArtists}
            />
        </>
    );
}

function ArtistsListWrapper({
    artists,
    nArtists,
    albumArtistOnly,
    onAlbumArtistOnlyChange,
    onAddArtist,
    canAddArtist = true,
    ...props
}: {
    artists: Array<Artist>;
    nArtists: number;
    albumArtistOnly: boolean;
    onAlbumArtistOnlyChange: (v: boolean) => void;
    onAddArtist: () => void;
    canAddArtist?: boolean;
} & BoxProps) {
    const [filter, setFilter] = useState<string>('');
    const [selected, setSelected] = useState<Set<string>>(new Set());
    const [confirmRemove, setConfirmRemove] = useState<string[] | null>(null);
    const queryClient = useQueryClient();

    const removeMutation = useMutation({
        mutationFn: async (names: string[]) => {
            await Promise.all(names.map((name) => removeTrackedArtist(name)));
        },
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['trackedArtists'] });
            void queryClient.invalidateQueries({ queryKey: ['artists'] });
            setSelected(new Set());
        },
    });

    const filteredData = useMemo(() => {
        if (!filter) return artists;
        return artists.filter((item) =>
            item.artist?.toLowerCase().includes(filter.toLowerCase())
        );
    }, [artists, filter]);

    const nRemovedByFilter = artists.length - filteredData.length;

    useEffect(() => {
        const visible = new Set(filteredData.map((a: Artist) => a.artist));
        setSelected((prev: Set<string>) => {
            const next = new Set([...prev].filter((name) => visible.has(name)));
            return next.size === prev.size ? prev : next;
        });
    }, [filteredData]);

    const selectedToRemove = useMemo(() => [...selected], [selected]);

    const handleToggleSelection = (artistName: string, checked: boolean) => {
        setSelected((prev: Set<string>) => {
            const next = new Set(prev);
            if (checked) next.add(artistName);
            else next.delete(artistName);
            return next;
        });
    };

    const handleToggleSelectAll = (checked: boolean, artistNames: string[]) => {
        setSelected((prev: Set<string>) => {
            const next = new Set(prev);
            if (checked) {
                for (const name of artistNames) next.add(name);
            } else {
                for (const name of artistNames) next.delete(name);
            }
            return next;
        });
    };

    const handleRemoveOne = (artistName: string) => {
        setConfirmRemove([artistName]);
    };

    const handleRemoveSelected = () => {
        if (selectedToRemove.length === 0) return;
        setConfirmRemove(selectedToRemove);
    };

    const handleConfirmRemove = () => {
        if (confirmRemove) removeMutation.mutate(confirmRemove);
        setConfirmRemove(null);
    };

    const bulkRefreshMissingMutation = useMutation({
        mutationFn: async (names: string[]) => {
            await Promise.allSettled(
                names.map(async (name) => {
                    const fresh = await fetchMissingAlbumsByArtist(name, true);
                    queryClient.setQueryData(missingAlbumsByArtistQueryOptions(name).queryKey, fresh);
                })
            );
        },
        onSettled: () => {
            void queryClient.invalidateQueries({ queryKey: ['artists'] });
            void queryClient.invalidateQueries({ queryKey: ['trackedArtists'] });
        },
    });

    const handleRefreshMissingSelected = () => {
        if (selected.size === 0) return;
        bulkRefreshMissingMutation.mutate([...selected]);
    };

    const confirmRemoveArtists = confirmRemove
        ? artists.filter((a) => confirmRemove.includes(a.artist))
        : [];
    const confirmHasAlbums = confirmRemoveArtists.some((a) => (a.album_count ?? 0) > 0);

    return (
        <Box {...props}>
            {/* Header row */}
            <Box
                sx={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1,
                    px: 2,
                    py: 1.5,
                    borderBottom: '1px solid',
                    borderColor: 'divider',
                }}
            >
                <ArtistIcon size={16} style={{ opacity: 0.5 }} />
                <Typography variant="subtitle2" fontWeight={700} sx={{ flex: 1 }}>
                    Artists
                </Typography>
                <Typography variant="caption" color="text.disabled">
                    {nArtists}
                </Typography>
                <Tooltip title={canAddArtist ? 'Add a new artist' : 'Permission required to add new artists'}>
                    <span>
                    <Button
                        size="small"
                        variant="outlined"
                        startIcon={<UserRoundPlusIcon size={14} />}
                        onClick={canAddArtist ? onAddArtist : undefined}
                        disabled={!canAddArtist}
                        sx={(theme) => ({
                            textTransform: 'none',
                            fontSize: 12,
                            [theme.breakpoints.down('tablet')]: {
                                minWidth: 0, px: 1,
                                '& .MuiButton-startIcon': { mr: 0 },
                            },
                        })}
                    >
                        <Box component="span" sx={(theme) => ({ [theme.breakpoints.down('tablet')]: { display: 'none' } })}>
                            Add Artist
                        </Box>
                    </Button>
                    </span>
                </Tooltip>
            </Box>

            {/* Toolbar */}
            <Box
                sx={(theme) => ({
                    display: 'flex',
                    gap: 1,
                    px: 2,
                    py: 1,
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    borderBottom: '1px solid',
                    borderColor: 'divider',
                    backgroundColor: 'background.paper',
                })}
            >
                <Search
                    value={filter}
                    setValue={setFilter}
                    size="small"
                    sx={(theme) => ({
                        flex: '1 1 auto',
                        maxWidth: 260,
                        [theme.breakpoints.down('tablet')]: { maxWidth: '100%', flex: '1 1 100%' },
                    })}
                />
                <FormControlLabel
                    control={
                        <Switch
                            size="small"
                            checked={albumArtistOnly}
                            onChange={(e) => onAlbumArtistOnlyChange(e.target.checked)}
                        />
                    }
                    label={<Typography variant="caption" color="text.secondary">Album artists</Typography>}
                    sx={{ m: 0, mr: 'auto' }}
                />
                <Box sx={{ display: 'flex', gap: 0.75 }}>
                    <Tooltip title={`Remove Selected (${selectedToRemove.length})`}>
                        <span>
                            <Button size="small" variant="outlined" color="error"
                                onClick={handleRemoveSelected}
                                disabled={selectedToRemove.length === 0 || removeMutation.isPending}
                                sx={(theme) => ({ textTransform: 'none', fontSize: 12, [theme.breakpoints.down('tablet')]: { minWidth: 0, px: 1, '& .MuiButton-startIcon': { mr: 0 } } })}
                                startIcon={removeMutation.isPending ? <CircularProgress size={12} /> : <Trash2Icon size={12} />}
                            >
                                <Box component="span" sx={(theme) => ({ [theme.breakpoints.down('tablet')]: { display: 'none' } })}>
                                    Remove ({selectedToRemove.length})
                                </Box>
                            </Button>
                        </span>
                    </Tooltip>
                    <Tooltip title={`Refresh missing albums for selected (${selected.size})`}>
                        <span>
                            <Button size="small" variant="outlined"
                                onClick={handleRefreshMissingSelected}
                                disabled={selected.size === 0 || bulkRefreshMissingMutation.isPending}
                                sx={(theme) => ({ textTransform: 'none', fontSize: 12, [theme.breakpoints.down('tablet')]: { minWidth: 0, px: 1, '& .MuiButton-startIcon': { mr: 0 } } })}
                                startIcon={bulkRefreshMissingMutation.isPending ? <CircularProgress size={12} /> : <RefreshCw size={12} />}
                            >
                                <Box component="span" sx={(theme) => ({ [theme.breakpoints.down('tablet')]: { display: 'none' } })}>
                                    Refresh ({selected.size})
                                </Box>
                            </Button>
                        </span>
                    </Tooltip>
                </Box>
                {nRemovedByFilter > 0 && (
                    <Typography variant="caption" color="text.disabled" sx={{ width: '100%' }}>
                        {nRemovedByFilter} artist{nRemovedByFilter > 1 ? 's' : ''} hidden by filter
                    </Typography>
                )}
            </Box>

            {/* Table */}
            <Box sx={{ overflow: 'auto', flex: '1 1 auto', minHeight: 0 }}>
                <ArtistsTable
                    artists={filteredData}
                    selected={selected}
                    onToggleSelection={handleToggleSelection}
                    onToggleSelectAll={handleToggleSelectAll}
                    onRemoveArtist={handleRemoveOne}
                    isRemovingArtist={(artistName) =>
                        removeMutation.isPending && (removeMutation.variables ?? []).includes(artistName)
                    }
                    disableActions={removeMutation.isPending}
                />
            </Box>

            {/* Confirm remove dialog */}
            <Dialog open={confirmRemove !== null} onClose={() => setConfirmRemove(null)} maxWidth="xs" fullWidth>
                <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Trash2Icon size={18} />
                    Remove {confirmRemove?.length === 1 ? 'Artist' : `${confirmRemove?.length ?? 0} Artists`}
                </DialogTitle>
                <DialogContent>
                    <DialogContentText>
                        {confirmRemove?.length === 1
                            ? `Remove "${confirmRemove[0]}" from the tracked list?`
                            : `Remove ${confirmRemove?.length ?? 0} artists from the tracked list?`}
                        {confirmHasAlbums && (
                            <Box component="span" sx={{ display: 'block', mt: 1, color: 'error.main', fontWeight: 600 }}>
                                This will permanently delete all associated albums and audio files from the library.
                            </Box>
                        )}
                    </DialogContentText>
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setConfirmRemove(null)}>Cancel</Button>
                    <Button color="error" variant="contained" onClick={handleConfirmRemove} disabled={removeMutation.isPending}>
                        {removeMutation.isPending ? <CircularProgress size={16} /> : 'Remove'}
                    </Button>
                </DialogActions>
            </Dialog>
        </Box>
    );
}

/* ──────────────────────── Add Artist Dialog ────────────────────────── */

function AddArtistDialog({
    open,
    onClose,
    trackedArtists,
}: {
    open: boolean;
    onClose: () => void;
    trackedArtists: TrackedArtist[];
}) {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState<ArtistSearchResult[]>([]);
    const [searching, setSearching] = useState(false);
    const [searchError, setSearchError] = useState<string | null>(null);
    const queryClient = useQueryClient();

    const trackedNames = useMemo(
        () => new Set(trackedArtists.map((a) => a.name.toLowerCase())),
        [trackedArtists]
    );

    const addMutation = useMutation({
        mutationFn: (artist: ArtistSearchResult) => addTrackedArtist(artist.name, artist.original_name),
        onSuccess: (_data, artist) => {
            void queryClient.invalidateQueries({ queryKey: ['trackedArtists'] });
            setResults((prev) =>
                prev.map((r) =>
                    r.name.toLowerCase() === artist.name.toLowerCase()
                        ? { ...r, tracked: true }
                        : r
                )
            );
        },
    });

    const removeMutation = useMutation({
        mutationFn: (name: string) => removeTrackedArtist(name),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['trackedArtists'] });
            void queryClient.invalidateQueries({ queryKey: ['artists'] });
        },
    });

    const handleSearch = async () => {
        if (!query.trim()) return;
        setSearching(true);
        setSearchError(null);
        try {
            const data = await searchArtists(query.trim());
            setResults(data);
        } catch (err) {
            setSearchError(err instanceof Error ? err.message : String(err));
            setResults([]);
        } finally {
            setSearching(false);
        }
    };

    const handleClose = () => {
        setQuery('');
        setResults([]);
        setSearchError(null);
        onClose();
    };

    return (
        <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
            <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <UserRoundPlusIcon size={20} />
                Add Artist
            </DialogTitle>
            <DialogContent>
                <Box sx={{ display: 'flex', gap: 1, mb: 2, mt: 0.5 }}>
                    <TextField
                        size="small"
                        placeholder="Search artist name…"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') void handleSearch();
                        }}
                        fullWidth
                        InputProps={{
                            startAdornment: (
                                <InputAdornment position="start">
                                    <SearchIcon size={16} />
                                </InputAdornment>
                            ),
                        }}
                        autoFocus
                    />
                    <Button
                        variant="contained"
                        onClick={() => void handleSearch()}
                        disabled={searching || !query.trim()}
                        sx={{ whiteSpace: 'nowrap' }}
                    >
                        {searching ? <CircularProgress size={16} /> : 'Search'}
                    </Button>
                </Box>
                {results.length > 0 && (
                    <List dense disablePadding>
                        {results.map((artist, idx) => {
                            const isTracked = artist.tracked || trackedNames.has(artist.name.toLowerCase());
                            return (
                                <ListItem
                                    key={artist.id ?? `deezer-${artist.deezer_id ?? idx}`}
                                    secondaryAction={
                                        isTracked ? (
                                            <Tooltip title="Remove">
                                                <IconButton
                                                    size="small"
                                                    color="success"
                                                    onClick={() => removeMutation.mutate(artist.name)}
                                                >
                                                    <CheckIcon size={16} />
                                                </IconButton>
                                            </Tooltip>
                                        ) : (
                                            <Tooltip title="Add">
                                                <IconButton
                                                    size="small"
                                                    onClick={() => addMutation.mutate(artist)}
                                                >
                                                    <UserRoundPlusIcon size={16} />
                                                </IconButton>
                                            </Tooltip>
                                        )
                                    }
                                    disablePadding
                                    sx={{ py: 0.5 }}
                                >
                                    <ListItemAvatar sx={{ minWidth: 44 }}>
                                        <Avatar sx={{ width: 36, height: 36 }}>
                                            {artist.name.charAt(0).toUpperCase()}
                                        </Avatar>
                                    </ListItemAvatar>
                                    <ListItemText
                                        primary={artist.name}
                                        secondary={
                                            (artist.disambiguation || artist.country || artist.mb_url) ? (
                                                <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
                                                    <span>
                                                        {[artist.disambiguation, artist.country].filter(Boolean).join(' · ')}
                                                    </span>
                                                    {artist.mb_url && (
                                                        <Tooltip title="View on MusicBrainz">
                                                            <Box
                                                                component="a"
                                                                href={artist.mb_url}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                onClick={(e) => e.stopPropagation()}
                                                                sx={{ color: 'text.disabled', display: 'inline-flex', '&:hover': { color: 'primary.main' } }}
                                                            >
                                                                <ExternalLinkIcon size={11} />
                                                            </Box>
                                                        </Tooltip>
                                                    )}
                                                </Box>
                                            ) : undefined
                                        }
                                    />
                                </ListItem>
                            );
                        })}
                    </List>
                )}
                {searchError && (
                    <Typography variant="body2" color="error" textAlign="center" sx={{ py: 2 }}>
                        {searchError}
                    </Typography>
                )}
                {results.length === 0 && !searching && !searchError && query && (
                    <Typography variant="body2" color="text.secondary" textAlign="center" sx={{ py: 2 }}>
                        No results. Try a different name.
                    </Typography>
                )}
            </DialogContent>
        </Dialog>
    );
}
