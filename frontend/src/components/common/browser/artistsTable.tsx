import { useState, useMemo } from 'react';
import {
    Table,
    TableBody,
    Checkbox,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    TableSortLabel,
    Box,
    Button,
    CircularProgress,
    Chip,
    Paper,
    Tooltip,
    Typography,
} from '@mui/material';
import { CheckIcon, UserRoundPlusIcon } from 'lucide-react';
import { Link } from '@tanstack/react-router';
import { Artist } from '@/api/library';

export interface ArtistsTableProps {
    artists: Artist[];
    selectedToFollow: Set<string>;
    onToggleSelection: (artistName: string, checked: boolean) => void;
    onToggleSelectAll: (checked: boolean, artistNames: string[]) => void;
    onFollowArtist: (artistName: string) => void;
    isFollowingArtist: (artistName: string) => boolean;
    disableActions?: boolean;
}

type SortField = 'artist' | 'album_count' | 'item_count' | 'total_size';
type SortOrder = 'asc' | 'desc';

export function ArtistsTable({
    artists,
    selectedToFollow,
    onToggleSelection,
    onToggleSelectAll,
    onFollowArtist,
    isFollowingArtist,
    disableActions = false,
}: ArtistsTableProps) {
    const [sortField, setSortField] = useState<SortField>('artist');
    const [sortOrder, setSortOrder] = useState<SortOrder>('asc');

    const sorted = useMemo(() => {
        const copy = [...artists];
        copy.sort((a, b) => {
            let aVal: string | number;
            let bVal: string | number;

            if (sortField === 'artist') {
                aVal = a.artist || 'Unknown';
                bVal = b.artist || 'Unknown';
            } else if (sortField === 'album_count') {
                aVal = a.album_count;
                bVal = b.album_count;
            } else if (sortField === 'item_count') {
                aVal = a.item_count;
                bVal = b.item_count;
            } else if (sortField === 'total_size') {
                aVal = a.total_size;
                bVal = b.total_size;
            } else {
                return 0;
            }

            if (typeof aVal === 'string' && typeof bVal === 'string') {
                return sortOrder === 'asc'
                    ? aVal.localeCompare(bVal)
                    : bVal.localeCompare(aVal);
            } else if (typeof aVal === 'number' && typeof bVal === 'number') {
                return sortOrder === 'asc' ? aVal - bVal : bVal - aVal;
            }
            return 0;
        });
        return copy;
    }, [artists, sortField, sortOrder]);

    const handleSort = (field: SortField) => {
        if (sortField === field) {
            setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
        } else {
            setSortField(field);
            setSortOrder('asc');
        }
    };

    const formatBytes = (bytes: number): string => {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    };

    const selectableArtists = sorted
        .filter((artist) => !artist.followed)
        .map((artist) => artist.artist);
    const selectedVisibleCount = selectableArtists.filter((name) =>
        selectedToFollow.has(name)
    ).length;
    const allSelectableChecked =
        selectableArtists.length > 0 &&
        selectedVisibleCount === selectableArtists.length;
    const someSelectableChecked =
        selectedVisibleCount > 0 &&
        selectedVisibleCount < selectableArtists.length;

    return (
        <TableContainer component={Paper}>
            <Table size="small">
                <TableHead>
                    <TableRow sx={{ backgroundColor: 'primary.light' }}>
                        <TableCell padding="checkbox" sx={{ width: 44 }}>
                            <Checkbox
                                size="small"
                                indeterminate={someSelectableChecked}
                                checked={allSelectableChecked}
                                disabled={selectableArtists.length === 0 || disableActions}
                                onChange={(e) =>
                                    onToggleSelectAll(
                                        e.target.checked,
                                        selectableArtists
                                    )
                                }
                                inputProps={{ 'aria-label': 'Select artists to follow' }}
                            />
                        </TableCell>
                        <TableCell>
                            <TableSortLabel
                                active={sortField === 'artist'}
                                direction={sortField === 'artist' ? sortOrder : 'asc'}
                                onClick={() => handleSort('artist')}
                            >
                                Artist
                            </TableSortLabel>
                        </TableCell>
                        <TableCell align="right">
                            <TableSortLabel
                                active={sortField === 'album_count'}
                                direction={sortField === 'album_count' ? sortOrder : 'asc'}
                                onClick={() => handleSort('album_count')}
                            >
                                Albums
                            </TableSortLabel>
                        </TableCell>
                        <TableCell align="right">
                            <TableSortLabel
                                active={sortField === 'item_count'}
                                direction={sortField === 'item_count' ? sortOrder : 'asc'}
                                onClick={() => handleSort('item_count')}
                            >
                                Tracks
                            </TableSortLabel>
                        </TableCell>
                        <TableCell align="right">
                            <TableSortLabel
                                active={sortField === 'total_size'}
                                direction={sortField === 'total_size' ? sortOrder : 'asc'}
                                onClick={() => handleSort('total_size')}
                            >
                                Size
                            </TableSortLabel>
                        </TableCell>
                        <TableCell align="center" sx={{ width: 160 }}>
                            <Tooltip title="Follow status">
                                <Box
                                    component="span"
                                    sx={{
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                    }}
                                >
                                    <UserRoundPlusIcon size={14} />
                                </Box>
                            </Tooltip>
                        </TableCell>
                    </TableRow>
                </TableHead>
                <TableBody>
                    {sorted.length === 0 ? (
                        <TableRow>
                            <TableCell colSpan={6} align="center">
                                <Typography color="textSecondary">
                                    No artists found
                                </Typography>
                            </TableCell>
                        </TableRow>
                    ) : (
                        sorted.map((artist) => (
                            <TableRow
                                key={artist.artist}
                                component={Link}
                                to="/library/browse/artists/$artist"
                                params={{ artist: artist.artist }}
                                sx={{
                                    cursor: 'pointer',
                                    textDecoration: 'none',
                                    opacity: artist.followed ? 0.75 : 1,
                                    '&:hover': {
                                        backgroundColor: 'action.hover',
                                    },
                                }}
                            >
                                <TableCell
                                    padding="checkbox"
                                    onClick={(e) => {
                                        e.preventDefault();
                                        e.stopPropagation();
                                    }}
                                >
                                    <Checkbox
                                        size="small"
                                        checked={selectedToFollow.has(artist.artist)}
                                        disabled={artist.followed || disableActions}
                                        onChange={(e) =>
                                            onToggleSelection(
                                                artist.artist,
                                                e.target.checked
                                            )
                                        }
                                        inputProps={{
                                            'aria-label': `Select ${artist.artist} for bulk follow`,
                                        }}
                                    />
                                </TableCell>
                                <TableCell>
                                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                        {artist.artist || 'Unknown Artist'}
                                        {artist.followed && (
                                            <Chip
                                                label="following"
                                                size="small"
                                                variant="outlined"
                                                color="primary"
                                                sx={{ height: 18, fontSize: '0.65rem' }}
                                            />
                                        )}
                                    </Box>
                                </TableCell>
                                <TableCell align="right">{artist.album_count}</TableCell>
                                <TableCell align="right">{artist.item_count}</TableCell>
                                <TableCell align="right">{formatBytes(artist.total_size)}</TableCell>
                                <TableCell
                                    align="center"
                                    onClick={(e) => {
                                        e.preventDefault();
                                        e.stopPropagation();
                                    }}
                                >
                                    {artist.followed ? (
                                        <Tooltip title="Followed">
                                            <Box
                                                sx={{
                                                    display: 'inline-flex',
                                                    alignItems: 'center',
                                                    color: 'success.main',
                                                }}
                                            >
                                                <CheckIcon size={16} />
                                            </Box>
                                        </Tooltip>
                                    ) : (
                                        <Button
                                            size="small"
                                            variant="outlined"
                                            onClick={() => onFollowArtist(artist.artist)}
                                            disabled={disableActions || isFollowingArtist(artist.artist)}
                                            startIcon={
                                                isFollowingArtist(artist.artist) ? (
                                                    <CircularProgress size={14} />
                                                ) : (
                                                    <UserRoundPlusIcon size={14} />
                                                )
                                            }
                                        >
                                            Follow
                                        </Button>
                                    )}
                                </TableCell>
                            </TableRow>
                        ))
                    )}
                </TableBody>
            </Table>
        </TableContainer>
    );
}
