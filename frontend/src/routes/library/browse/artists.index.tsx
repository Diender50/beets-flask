import { useEffect, useMemo, useState } from 'react';
import {
    Box,
    BoxProps,
    Button,
    CircularProgress,
    Dialog,
    DialogContent,
    DialogTitle,
    Divider,
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
    useTheme,
} from '@mui/material';
import { UserRoundMinusIcon, UserRoundPlusIcon, SearchIcon, XIcon, CheckIcon } from 'lucide-react';
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query';
import { createFileRoute } from '@tanstack/react-router';

import { Artist, artistsQueryOptions } from '@/api/library';
import {
    ArtistSearchResult,
    FollowedArtist,
    followArtist,
    followedArtistsQueryOptions,
    searchArtists,
    unfollowArtist,
} from '@/api/discovery';
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
    const { data: followedArtists = [] } = useQuery(followedArtistsQueryOptions());

    const [followDialogOpen, setFollowDialogOpen] = useState(false);
    const [albumArtistOnly, setAlbumArtistOnly] = useState(true);

    // Merge: library artists + followed artists not already in library
    const libraryNames = useMemo(
        () => new Set(libraryArtists.map((a) => a.artist.toLowerCase())),
        [libraryArtists]
    );
    const followedNames = useMemo(
        () => new Set(followedArtists.map((a) => a.name.toLowerCase())),
        [followedArtists]
    );

    const mergedArtists: Artist[] = useMemo(() => {
        const libraryWithFollowState: Artist[] = libraryArtists.map((artist) => ({
            ...artist,
            followed:
                Boolean(artist.followed) ||
                followedNames.has(artist.artist.toLowerCase()),
        }));

        const followedOnly: Artist[] = followedArtists
            .filter((f) => !libraryNames.has(f.name.toLowerCase()))
            .map((f) => ({
                artist: f.name,
                album_count: 0,
                item_count: 0,
                missing_count: f.missing_count ?? 0,
                total_size: 0,
                followed: true,
            }));
        return [...libraryWithFollowState, ...followedOnly];
    }, [libraryArtists, followedArtists, libraryNames, followedNames]);

    const displayedArtists = useMemo(() => {
        if (!albumArtistOnly) return mergedArtists;
        // Keep albumartists (album_count > 0) and followed-only artists
        return mergedArtists.filter((a) => (a.album_count ?? 0) > 0 || a.followed);
    }, [mergedArtists, albumArtistOnly]);

    return (
        <>
            <ArtistsHeader
                nArtists={displayedArtists.length}
                onAddArtist={() => setFollowDialogOpen(true)}
                sx={(theme) => ({
                    [theme.breakpoints.down('laptop')]: {
                        background: `linear-gradient(to bottom, transparent 0%, ${theme.palette.background.paper} 100%)`,
                    },
                })}
            />
            <Divider sx={{ backgroundColor: 'primary.muted' }} />
            <ArtistsListWrapper
                artists={displayedArtists}
                albumArtistOnly={albumArtistOnly}
                onAlbumArtistOnlyChange={setAlbumArtistOnly}
                sx={(theme) => ({
                    display: 'flex',
                    flexDirection: 'column',
                    height: '100%',
                    overflow: 'hidden',
                    [theme.breakpoints.down('laptop')]: {
                        background: `linear-gradient(to bottom, ${theme.palette.background.paper} 0%, transparent 100%)`,
                    },
                })}
            />
            <FollowArtistDialog
                open={followDialogOpen}
                onClose={() => setFollowDialogOpen(false)}
                followedArtists={followedArtists}
            />
        </>
    );
}

function ArtistsHeader({
    nArtists,
    onAddArtist,
    sx,
    ...props
}: { nArtists: number; onAddArtist: () => void } & BoxProps) {
    const theme = useTheme();
    return (
        <Box
            sx={[
                {
                    display: 'flex',
                    gap: 2,
                    alignItems: 'center',
                    padding: 2,
                },
                // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
                ...(Array.isArray(sx) ? sx : [sx]),
            ]}
            {...props}
        >
            <Box sx={{ display: 'flex', alignItems: 'center', height: '100%' }}>
                <ArtistIcon size={40} color={theme.palette.primary.main} />
            </Box>
            <Box sx={{ flex: '1 1 auto' }}>
                <Typography variant="h5" fontWeight="bold" lineHeight={1}>
                    Browse Artists
                </Typography>
                <Typography variant="subtitle1" color="text.secondary">
                    {nArtists} unique artists
                </Typography>
            </Box>
            <Tooltip title="Follow artist">
                <Button
                    variant="outlined"
                    size="small"
                    startIcon={<UserRoundPlusIcon size={16} />}
                    onClick={onAddArtist}
                >
                    Follow Artist
                </Button>
            </Tooltip>
        </Box>
    );
}

function ArtistsListWrapper({
    artists,
    albumArtistOnly,
    onAlbumArtistOnlyChange,
    ...props
}: { artists: Array<Artist>; albumArtistOnly: boolean; onAlbumArtistOnlyChange: (v: boolean) => void } & BoxProps) {
    const [filter, setFilter] = useState<string>('');
    const [selected, setSelected] = useState<Set<string>>(new Set());
    const queryClient = useQueryClient();

    const followMutation = useMutation({
        mutationFn: (name: string) => followArtist(name),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['followedArtists'] });
        },
    });

    const bulkFollowMutation = useMutation({
        mutationFn: async (names: string[]) => {
            await Promise.all(names.map((name) => followArtist(name)));
        },
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['followedArtists'] });
        },
    });

    const unfollowMutation = useMutation({
        mutationFn: (name: string) => unfollowArtist(name),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['followedArtists'] });
        },
    });

    const bulkUnfollowMutation = useMutation({
        mutationFn: async (names: string[]) => {
            await Promise.all(names.map((name) => unfollowArtist(name)));
        },
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['followedArtists'] });
        },
    });

    const filteredData = useMemo(() => {
        if (!filter) return artists;
        return artists.filter((item) =>
            item.artist?.toLowerCase().includes(filter.toLowerCase())
        );
    }, [artists, filter]);

    const nRemovedByFilter = artists.length - filteredData.length;

    // Remove selected artists that scrolled out of the visible set.
    useEffect(() => {
        const visible = new Set(filteredData.map((a: Artist) => a.artist));
        setSelected((prev: Set<string>) => {
            const next = new Set([...prev].filter((name) => visible.has(name)));
            return next.size === prev.size ? prev : next;
        });
    }, [filteredData]);

    const followedNames = useMemo(
        () => new Set(filteredData.filter((a: Artist) => a.followed).map((a: Artist) => a.artist)),
        [filteredData]
    );

    const selectedToFollow = useMemo(
        () => [...selected].filter((name) => !followedNames.has(name)),
        [selected, followedNames]
    );
    const selectedToUnfollow = useMemo(
        () => [...selected].filter((name) => followedNames.has(name)),
        [selected, followedNames]
    );

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

    const handleFollowOne = (artistName: string) => {
        followMutation.mutate(artistName);
    };

    const handleFollowSelected = () => {
        if (selectedToFollow.length === 0) return;
        bulkFollowMutation.mutate(selectedToFollow);
    };

    const handleUnfollowOne = (artistName: string) => {
        unfollowMutation.mutate(artistName);
    };

    const handleUnfollowSelected = () => {
        if (selectedToUnfollow.length === 0) return;
        bulkUnfollowMutation.mutate(selectedToUnfollow);
    };

    return (
        <Box {...props}>
            <Box
                sx={(theme) => ({
                    display: 'flex',
                    gap: 2,
                    width: '100%',
                    padding: 2,
                    flexWrap: 'wrap',
                    alignItems: 'center',
                    [theme.breakpoints.down(500)]: {
                        flexDirection: 'column',
                        alignItems: 'flex-start',
                        gap: 2,
                    },
                })}
            >
                <Search
                    value={filter}
                    setValue={setFilter}
                    size="small"
                    sx={{
                        flex: '1 1 auto',
                        maxWidth: 300,
                        flexGrow: 1,
                    }}
                />
                <FormControlLabel
                    control={
                        <Switch
                            size="small"
                            checked={albumArtistOnly}
                            onChange={(e) => onAlbumArtistOnlyChange(e.target.checked)}
                        />
                    }
                    label={
                        <Typography variant="body2" color="text.secondary">
                            Album artists only
                        </Typography>
                    }
                />
                <Button
                    size="small"
                    variant="outlined"
                    onClick={handleFollowSelected}
                    disabled={
                        selectedToFollow.length === 0 ||
                        followMutation.isPending ||
                        bulkFollowMutation.isPending
                    }
                    startIcon={
                        bulkFollowMutation.isPending ? (
                            <CircularProgress size={14} />
                        ) : (
                            <UserRoundPlusIcon size={14} />
                        )
                    }
                >
                    Follow Selected ({selectedToFollow.length})
                </Button>
                <Button
                    size="small"
                    variant="outlined"
                    color="error"
                    onClick={handleUnfollowSelected}
                    disabled={
                        selectedToUnfollow.length === 0 ||
                        unfollowMutation.isPending ||
                        bulkUnfollowMutation.isPending
                    }
                    startIcon={
                        bulkUnfollowMutation.isPending ? (
                            <CircularProgress size={14} />
                        ) : (
                            <UserRoundMinusIcon size={14} />
                        )
                    }
                >
                    Unfollow Selected ({selectedToUnfollow.length})
                </Button>
                <Typography
                    variant="caption"
                    color="text.secondary"
                    visibility={nRemovedByFilter > 0 ? 'visible' : 'hidden'}
                >
                    {nRemovedByFilter}
                    {' artist'}
                    {nRemovedByFilter > 1 && 's'} hidden by filter
                </Typography>
            </Box>
            <Box
                sx={{
                    overflow: 'auto',
                    flex: '1 1 auto',
                    paddingInline: 2,
                    minHeight: 0,
                }}
            >
                <ArtistsTable
                    artists={filteredData}
                    selected={selected}
                    onToggleSelection={handleToggleSelection}
                    onToggleSelectAll={handleToggleSelectAll}
                    onFollowArtist={handleFollowOne}
                    isFollowingArtist={(artistName) =>
                        followMutation.isPending &&
                        followMutation.variables === artistName
                    }
                    onUnfollowArtist={handleUnfollowOne}
                    isUnfollowingArtist={(artistName) =>
                        unfollowMutation.isPending &&
                        unfollowMutation.variables === artistName
                    }
                    disableActions={bulkFollowMutation.isPending || bulkUnfollowMutation.isPending}
                />
            </Box>
        </Box>
    );
}

/* ─────────────────────── Follow Artist Dialog ───────────────────────── */

function FollowArtistDialog({
    open,
    onClose,
    followedArtists,
}: {
    open: boolean;
    onClose: () => void;
    followedArtists: FollowedArtist[];
}) {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState<ArtistSearchResult[]>([]);
    const [searching, setSearching] = useState(false);
    const [searchError, setSearchError] = useState<string | null>(null);
    const queryClient = useQueryClient();

    const followedNames = useMemo(
        () => new Set(followedArtists.map((a) => a.name.toLowerCase())),
        [followedArtists]
    );

    const followMutation = useMutation({
        mutationFn: (name: string) => followArtist(name),
        onSuccess: (_data, name) => {
            void queryClient.invalidateQueries({ queryKey: ['followedArtists'] });
            // Update result list to reflect follow state
            setResults((prev) =>
                prev.map((r) =>
                    r.name.toLowerCase() === name.toLowerCase()
                        ? { ...r, followed: true }
                        : r
                )
            );
        },
    });

    const unfollowMutation = useMutation({
        mutationFn: (name: string) => unfollowArtist(name),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['followedArtists'] });
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
                Follow Artist
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
                        {results.map((artist) => {
                            const isFollowed =
                                artist.followed ||
                                followedNames.has(artist.name.toLowerCase());
                            return (
                                <ListItem
                                    key={artist.id}
                                    secondaryAction={
                                        isFollowed ? (
                                            <Tooltip title="Unfollow">
                                                <IconButton
                                                    size="small"
                                                    color="success"
                                                    onClick={() =>
                                                        unfollowMutation.mutate(artist.name)
                                                    }
                                                >
                                                    <CheckIcon size={16} />
                                                </IconButton>
                                            </Tooltip>
                                        ) : (
                                            <Tooltip title="Follow">
                                                <IconButton
                                                    size="small"
                                                    onClick={() =>
                                                        followMutation.mutate(artist.name)
                                                    }
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
                                            [artist.disambiguation, artist.country]
                                                .filter(Boolean)
                                                .join(' · ') || undefined
                                        }
                                    />
                                </ListItem>
                            );
                        })}
                    </List>
                )}
                {searchError && (
                    <Typography
                        variant="body2"
                        color="error"
                        textAlign="center"
                        sx={{ py: 2 }}
                    >
                        {searchError}
                    </Typography>
                )}
                {results.length === 0 && !searching && !searchError && query && (
                    <Typography
                        variant="body2"
                        color="text.secondary"
                        textAlign="center"
                        sx={{ py: 2 }}
                    >
                        No results. Try a different name.
                    </Typography>
                )}
            </DialogContent>
        </Dialog>
    );
}
