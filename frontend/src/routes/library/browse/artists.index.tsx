import { useMemo, useState } from 'react';
import {
    Box,
    BoxProps,
    Button,
    CircularProgress,
    Dialog,
    DialogContent,
    DialogTitle,
    Divider,
    IconButton,
    InputAdornment,
    List,
    ListItem,
    ListItemAvatar,
    ListItemText,
    Avatar,
    TextField,
    Tooltip,
    Typography,
    useTheme,
} from '@mui/material';
import { UserRoundPlusIcon, SearchIcon, XIcon, CheckIcon } from 'lucide-react';
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

    // Merge: library artists + followed artists not already in library
    const libraryNames = useMemo(
        () => new Set(libraryArtists.map((a) => a.artist.toLowerCase())),
        [libraryArtists]
    );

    const mergedArtists: Artist[] = useMemo(() => {
        const followedOnly: Artist[] = followedArtists
            .filter((f) => !libraryNames.has(f.name.toLowerCase()))
            .map((f) => ({
                artist: f.name,
                album_count: 0,
                item_count: 0,
                total_size: 0,
                followed: true,
            }));
        return [...libraryArtists, ...followedOnly];
    }, [libraryArtists, followedArtists, libraryNames]);

    return (
        <>
            <ArtistsHeader
                nArtists={mergedArtists.length}
                onAddArtist={() => setFollowDialogOpen(true)}
                sx={(theme) => ({
                    [theme.breakpoints.down('laptop')]: {
                        background: `linear-gradient(to bottom, transparent 0%, ${theme.palette.background.paper} 100%)`,
                    },
                })}
            />
            <Divider sx={{ backgroundColor: 'primary.muted' }} />
            <ArtistsListWrapper
                artists={mergedArtists}
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
    ...props
}: { artists: Array<Artist> } & BoxProps) {
    const [filter, setFilter] = useState<string>('');

    const filteredData = useMemo(() => {
        if (!filter) {
            return artists;
        }
        return artists.filter((item) => {
            return item.artist?.toLowerCase().includes(filter.toLowerCase());
        });
    }, [artists, filter]);

    const nRemovedByFilter = artists.length - filteredData.length;

    return (
        <Box {...props}>
            <Box
                sx={(theme) => ({
                    display: 'flex',
                    gap: 4,
                    width: '100%',
                    padding: 2,
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
                <ArtistsTable artists={filteredData} />
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
