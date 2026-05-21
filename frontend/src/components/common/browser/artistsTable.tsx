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
    IconButton,
    Tooltip,
    Typography,
} from '@mui/material';
import { CheckIcon, UserRoundMinusIcon, UserRoundPlusIcon } from 'lucide-react';
import { Link } from '@tanstack/react-router';
import { Artist } from '@/api/library';

export interface ArtistsTableProps {
    artists: Artist[];
    selected: Set<string>;
    onToggleSelection: (artistName: string, checked: boolean) => void;
    onToggleSelectAll: (checked: boolean, artistNames: string[]) => void;
    onFollowArtist: (artistName: string) => void;
    isFollowingArtist: (artistName: string) => boolean;
    onUnfollowArtist: (artistName: string) => void;
    isUnfollowingArtist: (artistName: string) => boolean;
    disableActions?: boolean;
}

type SortField = 'artist' | 'album_count' | 'item_count' | 'missing_count' | 'total_size';
type SortOrder = 'asc' | 'desc';

const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '—';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
};

export function ArtistsTable({
    artists,
    selected,
    onToggleSelection,
    onToggleSelectAll,
    onFollowArtist,
    isFollowingArtist,
    onUnfollowArtist,
    isUnfollowingArtist,
    disableActions = false,
}: ArtistsTableProps) {
    const [sortField, setSortField] = useState<SortField>('artist');
    const [sortOrder, setSortOrder] = useState<SortOrder>('asc');

    const sorted = useMemo(() => {
        const copy = [...artists];
        copy.sort((a, b) => {
            let aVal: string | number;
            let bVal: string | number;
            if (sortField === 'artist') { aVal = a.artist || ''; bVal = b.artist || ''; }
            else if (sortField === 'album_count') { aVal = a.album_count; bVal = b.album_count; }
            else if (sortField === 'item_count') { aVal = a.item_count; bVal = b.item_count; }
            else if (sortField === 'missing_count') { aVal = a.missing_count ?? 0; bVal = b.missing_count ?? 0; }
            else { aVal = a.total_size; bVal = b.total_size; }
            if (typeof aVal === 'string') return sortOrder === 'asc' ? aVal.localeCompare(bVal as string) : (bVal as string).localeCompare(aVal);
            return sortOrder === 'asc' ? (aVal as number) - (bVal as number) : (bVal as number) - (aVal as number);
        });
        return copy;
    }, [artists, sortField, sortOrder]);

    const handleSort = (field: SortField) => {
        if (sortField === field) setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
        else { setSortField(field); setSortOrder('asc'); }
    };

    const allNames = sorted.map((a: Artist) => a.artist);
    const selectedVisibleCount = allNames.filter((n: string) => selected.has(n)).length;
    const allChecked = allNames.length > 0 && selectedVisibleCount === allNames.length;
    const someChecked = selectedVisibleCount > 0 && selectedVisibleCount < allNames.length;

    const colHeader = {
        fontSize: 11,
        fontWeight: 600,
        textTransform: 'uppercase' as const,
        letterSpacing: '0.05em',
        color: 'text.disabled',
    };

    return (
        <TableContainer sx={{ background: 'transparent' }}>
            <Table size="small" sx={{ minWidth: 0, width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
                <TableHead>
                    <TableRow>
                        <TableCell padding="checkbox" sx={{ width: 40, border: 'none', pb: 0.5 }}>
                            <Checkbox
                                size="small"
                                indeterminate={someChecked}
                                checked={allChecked}
                                disabled={allNames.length === 0 || disableActions}
                                onChange={(e: { target: { checked: boolean } }) =>
                                    onToggleSelectAll(e.target.checked, allNames)
                                }
                            />
                        </TableCell>
                        <TableCell sx={{ border: 'none', pb: 0.5, width: '100%' }}>
                            <TableSortLabel
                                active={sortField === 'artist'}
                                direction={sortField === 'artist' ? sortOrder : 'asc'}
                                onClick={() => handleSort('artist')}
                                sx={colHeader}
                            >
                                Artist
                            </TableSortLabel>
                        </TableCell>
                        <TableCell align="right" sx={{ border: 'none', pb: 0.5, '@media (max-width: 639px)': { display: 'none' } }}>
                            <TableSortLabel active={sortField === 'album_count'} direction={sortField === 'album_count' ? sortOrder : 'asc'} onClick={() => handleSort('album_count')} sx={colHeader}>
                                Albums
                            </TableSortLabel>
                        </TableCell>
                        <TableCell align="right" sx={{ border: 'none', pb: 0.5, '@media (max-width: 639px)': { display: 'none' } }}>
                            <TableSortLabel active={sortField === 'item_count'} direction={sortField === 'item_count' ? sortOrder : 'asc'} onClick={() => handleSort('item_count')} sx={colHeader}>
                                Tracks
                            </TableSortLabel>
                        </TableCell>
                        <TableCell align="right" sx={{ border: 'none', pb: 0.5, width: 80 }}>
                            <TableSortLabel active={sortField === 'missing_count'} direction={sortField === 'missing_count' ? sortOrder : 'asc'} onClick={() => handleSort('missing_count')} sx={colHeader}>
                                Missing
                            </TableSortLabel>
                        </TableCell>
                        <TableCell align="right" sx={{ border: 'none', pb: 0.5, '@media (max-width: 639px)': { display: 'none' } }}>
                            <TableSortLabel active={sortField === 'total_size'} direction={sortField === 'total_size' ? sortOrder : 'asc'} onClick={() => handleSort('total_size')} sx={colHeader}>
                                Size
                            </TableSortLabel>
                        </TableCell>
                        <TableCell sx={{ border: 'none', pb: 0.5, width: 48 }} />
                    </TableRow>
                </TableHead>
                <TableBody>
                    {sorted.length === 0 ? (
                        <TableRow>
                            <TableCell colSpan={7} align="center" sx={{ border: 'none', py: 6 }}>
                                <Typography variant="body2" color="text.disabled">No artists found</Typography>
                            </TableCell>
                        </TableRow>
                    ) : sorted.map((artist: Artist) => (
                        <TableRow
                            key={artist.artist}
                            component={Link}
                            to="/library/browse/artists/$artist"
                            params={{ artist: artist.artist }}
                            sx={{
                                cursor: 'pointer',
                                textDecoration: 'none',
                                borderBottom: '1px solid',
                                borderColor: 'divider',
                                transition: 'background-color 0.1s',
                                '&:hover': { backgroundColor: 'action.hover' },
                                '&:last-child': { borderBottom: 'none' },
                            }}
                        >
                            <TableCell
                                padding="checkbox"
                                sx={{ border: 'none', py: 0.75 }}
                                onClick={(e: { stopPropagation: () => void }) => e.stopPropagation()}
                            >
                                <Checkbox
                                    size="small"
                                    checked={selected.has(artist.artist)}
                                    disabled={disableActions}
                                    onChange={(_e: unknown, checked: boolean) =>
                                        onToggleSelection(artist.artist, checked)
                                    }
                                />
                            </TableCell>
                            <TableCell sx={{ border: 'none', py: 0.75 }}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
                                    <Typography
                                        variant="body2"
                                        sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                                    >
                                        {artist.artist || 'Unknown Artist'}
                                    </Typography>
                                    {artist.followed && (
                                        <Tooltip title="Following">
                                            <Box component="span" sx={{ color: 'success.main', display: 'flex', flexShrink: 0 }}>
                                                <CheckIcon size={12} />
                                            </Box>
                                        </Tooltip>
                                    )}
                                </Box>
                            </TableCell>
                            <TableCell align="right" sx={{ border: 'none', py: 0.75, '@media (max-width: 639px)': { display: 'none' } }}>
                                <Typography variant="caption" color="text.secondary">{artist.album_count || '—'}</Typography>
                            </TableCell>
                            <TableCell align="right" sx={{ border: 'none', py: 0.75, '@media (max-width: 639px)': { display: 'none' } }}>
                                <Typography variant="caption" color="text.secondary">{artist.item_count || '—'}</Typography>
                            </TableCell>
                            <TableCell align="right" sx={{ border: 'none', py: 0.75 }}>
                                <Typography variant="caption" color={artist.missing_count ? 'text.secondary' : 'text.disabled'}>
                                    {artist.missing_count ?? '—'}
                                </Typography>
                            </TableCell>
                            <TableCell align="right" sx={{ border: 'none', py: 0.75, '@media (max-width: 639px)': { display: 'none' } }}>
                                <Typography variant="caption" color="text.disabled">{formatBytes(artist.total_size)}</Typography>
                            </TableCell>
                            <TableCell
                                align="center"
                                sx={{ border: 'none', py: 0.75, width: 48, overflow: 'hidden', p: 0.5 }}
                                onClick={(e: { preventDefault: () => void; stopPropagation: () => void }) => {
                                    e.preventDefault(); e.stopPropagation();
                                }}
                            >
                                {artist.followed ? (
                                    <Tooltip title="Unfollow">
                                        <IconButton
                                            size="small"
                                            color="error"
                                            onClick={() => onUnfollowArtist(artist.artist)}
                                            disabled={disableActions || isUnfollowingArtist(artist.artist)}
                                            sx={{ opacity: 0.7, '&:hover': { opacity: 1 } }}
                                        >
                                            <UserRoundMinusIcon size={14} />
                                        </IconButton>
                                    </Tooltip>
                                ) : (
                                    <Tooltip title="Follow">
                                        <IconButton
                                            size="small"
                                            onClick={() => onFollowArtist(artist.artist)}
                                            disabled={disableActions || isFollowingArtist(artist.artist)}
                                            sx={{ opacity: 0.4, '&:hover': { opacity: 1 } }}
                                        >
                                            <UserRoundPlusIcon size={14} />
                                        </IconButton>
                                    </Tooltip>
                                )}
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </TableContainer>
    );
}
