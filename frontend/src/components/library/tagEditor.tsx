/**
 * Album tag editor — fetches album+items on open, two-tab modal:
 *   Album  : property/value list (title, artist, year, genre, label)
 *   Tracks : inline-editable track rows (matching album.tsx Tracklist style)
 *
 * Save button is wired to a TODO stub; backend endpoint not yet implemented.
 */
import { Suspense, useCallback, useState } from 'react';
import { PencilIcon } from 'lucide-react';
import {
    Box,
    Button,
    CircularProgress,
    DialogContent,
    IconButton,
    Tab,
    Tabs,
    TextField,
    Tooltip,
    Typography,
    useMediaQuery,
    useTheme,
} from '@mui/material';
import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query';

import { Dialog } from '@/components/common/dialogs';
import { CoverArt } from '@/components/library/coverArt';
import { albumQueryOptions, updateAlbumTags } from '@/api/library';
import type { AlbumResponseExpanded, ItemResponse } from '@/pythonTypes';

// ── Local form types ─────────────────────────────────────────────────────────

interface AlbumFields {
    album: string;
    albumartist: string;
    year: string;
    genre: string;
    label: string;
}

interface TrackFields {
    id: number;
    name: string;
    artist: string;
    track: string;
}

// ── Shared input styling ──────────────────────────────────────────────────────

/** Base number-spinner suppression applied to all inputs. */
const NO_SPINNER_SX = {
    '& input[type=number]::-webkit-outer-spin-button': {
        WebkitAppearance: 'none' as const,
        margin: 0,
    },
    '& input[type=number]::-webkit-inner-spin-button': {
        WebkitAppearance: 'none' as const,
        margin: 0,
    },
    '& input[type=number]': { MozAppearance: 'textfield' as const },
} as const;

/** Base style for a single input element. */
const INPUT_BASE = {
    fontSize: '0.875rem',
    py: 0.5,
    px: 0.75,
    borderRadius: 0.5,
    background: 'rgba(255,255,255,0.04)',
    transition: 'background 0.12s',
};

/** Editable field: subtle tinted background makes the input clearly distinct
 *  from static text, without the weight of an outlined box. */
const FIELD_SX = {
    ...NO_SPINNER_SX,
    '& .MuiInputBase-input': INPUT_BASE,
    '& .MuiInputBase-root:hover .MuiInputBase-input': {
        background: 'rgba(255,255,255,0.07)',
    },
    '& .Mui-focused .MuiInputBase-input': {
        background: 'rgba(255,255,255,0.08)',
        outline: '1px solid rgba(255,255,255,0.12)',
    },
} as const;

// ── Public: edit button ───────────────────────────────────────────────────────

export function AlbumEditButton({ albumId }: { albumId: number }) {
    const [open, setOpen] = useState(false);

    return (
        <>
            <Tooltip title="Edit tags">
                <IconButton
                    size="small"
                    onClick={(e) => {
                        e.stopPropagation();
                        setOpen(true);
                    }}
                    sx={{ opacity: 0.5, '&:hover': { opacity: 1 }, padding: 0.5 }}
                    aria-label="Edit album tags"
                >
                    <PencilIcon size={14} />
                </IconButton>
            </Tooltip>

            {open && (
                <Suspense
                    fallback={
                        <Dialog
                            open
                            title="Loading…"
                            onClose={() => setOpen(false)}
                        >
                            <DialogContent
                                sx={{
                                    display: 'flex',
                                    justifyContent: 'center',
                                    py: 6,
                                }}
                            >
                                <CircularProgress size={28} />
                            </DialogContent>
                        </Dialog>
                    }
                >
                    <AlbumTagEditorDialog
                        albumId={albumId}
                        open={open}
                        onClose={() => setOpen(false)}
                    />
                </Suspense>
            )}
        </>
    );
}

// ── Dialog ────────────────────────────────────────────────────────────────────

function AlbumTagEditorDialog({
    albumId,
    open,
    onClose,
}: {
    albumId: number;
    open: boolean;
    onClose: () => void;
}) {
    const { data: album } = useSuspenseQuery(
        albumQueryOptions(albumId, true, false)
    );
    const expanded = album as AlbumResponseExpanded;
    const items: ItemResponse[] = expanded.items ?? [];

    const [tab, setTab] = useState(0);

    const [albumFields, setAlbumFields] = useState<AlbumFields>(() => ({
        album: expanded.name ?? '',
        albumartist: expanded.albumartist ?? '',
        year: String(expanded.year ?? ''),
        genre: expanded.genre ?? '',
        label: expanded.label ?? '',
    }));

    const [trackFields, setTrackFields] = useState<Map<number, TrackFields>>(
        () =>
            new Map(
                items.map((item) => [
                    item.id,
                    {
                        id: item.id,
                        name: item.name ?? '',
                        artist: item.artist ?? '',
                        track: String(item.track ?? ''),
                    },
                ])
            )
    );

    const sortedItems = [...items].sort(
        (a, b) => (a.track ?? 0) - (b.track ?? 0)
    );

    const queryClient = useQueryClient();

    const saveMutation = useMutation({
        mutationFn: () =>
            updateAlbumTags(albumId, {
                album: albumFields.album || undefined,
                albumartist: albumFields.albumartist || undefined,
                year: albumFields.year ? Number(albumFields.year) : undefined,
                genre: albumFields.genre || undefined,
                label: albumFields.label || undefined,
                tracks: [...trackFields.values()].map((f) => ({
                    id: f.id,
                    name: f.name || undefined,
                    artist: f.artist || undefined,
                    track: f.track ? Number(f.track) : undefined,
                })),
            }),
        onSuccess: () => {
            // Invalidate this album and all album list queries
            void queryClient.invalidateQueries({ queryKey: ['album', albumId] });
            void queryClient.invalidateQueries({ queryKey: ['albums'] });
            void queryClient.invalidateQueries({ queryKey: ['artists'] });
            onClose();
        },
    });

    const setAlbumField = useCallback(
        <K extends keyof AlbumFields>(field: K, value: AlbumFields[K]) =>
            setAlbumFields((prev) => ({ ...prev, [field]: value })),
        []
    );

    const setTrackField = useCallback(
        <K extends keyof TrackFields>(
            id: number,
            field: K,
            value: TrackFields[K]
        ) =>
            setTrackFields((prev) => {
                const next = new Map(prev);
                const cur = next.get(id);
                if (cur) next.set(id, { ...cur, [field]: value });
                return next;
            }),
        []
    );

    const handleSave = () => saveMutation.mutate();

    return (
        <Dialog
            open={open}
            onClose={(_, reason) => {
                if (reason !== 'backdropClick') onClose();
            }}
            title={expanded.name}
            title_icon={
                <CoverArt
                    type="album"
                    beetsId={albumId}
                    sx={{
                        width: 36,
                        height: 36,
                        borderRadius: 0.5,
                        flexShrink: 0,
                        objectFit: 'cover',
                    }}
                />
            }
        >
            <Box sx={{ borderBottom: 1, borderColor: 'divider', px: 2 }}>
                <Tabs
                    value={tab}
                    onChange={(_, v: number) => setTab(v)}
                    textColor="primary"
                    indicatorColor="primary"
                >
                    <Tab
                        label="Album"
                        sx={{ minHeight: 40, py: 0.5, fontSize: '0.8rem' }}
                    />
                    <Tab
                        label={`Tracks (${items.length})`}
                        sx={{ minHeight: 40, py: 0.5, fontSize: '0.8rem' }}
                    />
                </Tabs>
            </Box>

            <DialogContent sx={{ p: 0, overflow: 'auto' }}>
                {tab === 0 && (
                    <AlbumFieldsPanel
                        fields={albumFields}
                        onChange={setAlbumField}
                    />
                )}
                {tab === 1 && (
                    <TrackListPanel
                        items={sortedItems}
                        fields={trackFields}
                        onChange={setTrackField}
                        albumArtist={expanded.albumartist}
                    />
                )}
            </DialogContent>

            <Box
                sx={{
                    display: 'flex',
                    justifyContent: 'flex-end',
                    gap: 1,
                    px: 2,
                    py: 1.5,
                    borderTop: '1px solid',
                    borderColor: 'divider',
                }}
            >
                <Button
                    onClick={onClose}
                    color="inherit"
                    size="small"
                    disabled={saveMutation.isPending}
                >
                    Cancel
                </Button>
                <Button
                    variant="contained"
                    size="small"
                    onClick={handleSave}
                    disabled={saveMutation.isPending}
                    startIcon={
                        saveMutation.isPending ? (
                            <CircularProgress size={12} color="inherit" />
                        ) : undefined
                    }
                >
                    {saveMutation.isPending ? 'Saving…' : 'Save'}
                </Button>
                {saveMutation.isError && (
                    <Typography
                        variant="caption"
                        color="error"
                        sx={{ alignSelf: 'center', ml: 1 }}
                    >
                        {(saveMutation.error as Error).message}
                    </Typography>
                )}
            </Box>
        </Dialog>
    );
}

// ── Album fields panel ────────────────────────────────────────────────────────

const ALBUM_FIELDS = [
    { key: 'album',       label: 'Album',        type: 'text'   },
    { key: 'albumartist', label: 'Album artist',  type: 'text'   },
    { key: 'year',        label: 'Year',          type: 'number' },
    { key: 'genre',       label: 'Genre',         type: 'text'   },
    { key: 'label',       label: 'Label',         type: 'text'   },
] as const;

function AlbumFieldsPanel({
    fields,
    onChange,
}: {
    fields: AlbumFields;
    onChange: <K extends keyof AlbumFields>(
        field: K,
        value: AlbumFields[K]
    ) => void;
}) {
    const isMobile = useMediaQuery((theme) => theme.breakpoints.down('tablet'));

    return (
        <Box sx={{ px: 2, py: 1 }}>
            {ALBUM_FIELDS.map(({ key, label, type }, i) => (
                <Box
                    key={key}
                    sx={{
                        display: 'flex',
                        flexDirection: isMobile ? 'column' : 'row',
                        alignItems: isMobile ? 'flex-start' : 'center',
                        py: isMobile ? 1.25 : 1,
                        gap: isMobile ? 0.25 : 2,
                        borderBottom:
                            i < ALBUM_FIELDS.length - 1 ? '1px solid' : 'none',
                        borderColor: 'divider',
                    }}
                >
                    <Typography
                        variant="caption"
                        sx={{
                            width: isMobile ? 'auto' : 100,
                            flexShrink: 0,
                            color: 'text.disabled',
                            textTransform: 'uppercase',
                            letterSpacing: '0.06em',
                            fontSize: '0.65rem',
                            fontWeight: 600,
                        }}
                    >
                        {label}
                    </Typography>
                    <TextField
                        fullWidth
                        variant="standard"
                        type={type}
                        value={fields[key]}
                        onChange={(e) => onChange(key, e.target.value)}
                        size="small"
                        slotProps={{ input: { disableUnderline: true } }}
                        sx={FIELD_SX}
                    />
                </Box>
            ))}
        </Box>
    );
}

// ── Track list panel ──────────────────────────────────────────────────────────

function TrackListPanel({
    items,
    fields,
    onChange,
    albumArtist,
}: {
    items: ItemResponse[];
    fields: Map<number, TrackFields>;
    onChange: <K extends keyof TrackFields>(
        id: number,
        field: K,
        value: TrackFields[K]
    ) => void;
    albumArtist: string;
}) {
    const theme = useTheme();
    const isMobile = useMediaQuery((t) => t.breakpoints.down('tablet'));

    if (items.length === 0) {
        return (
            <Typography
                color="text.secondary"
                sx={{ py: 6, textAlign: 'center', fontSize: '0.875rem' }}
            >
                No tracks available.
            </Typography>
        );
    }

    const gridCols = isMobile ? '28px 1fr' : '28px 1fr 1fr';

    const focusSx = {
        '& .MuiInputBase-root:hover .MuiInputBase-input': {
            background: 'rgba(255,255,255,0.07)',
        },
        '& .Mui-focused .MuiInputBase-input': {
            background: 'rgba(255,255,255,0.08)',
            outline: '1px solid rgba(255,255,255,0.12)',
        },
    };

    const artistInputSx = (isVarious: boolean) => ({
        ...NO_SPINNER_SX,
        ...focusSx,
        '& .MuiInputBase-input': {
            ...INPUT_BASE,
            color: isVarious
                ? theme.palette.text.primary
                : theme.palette.text.secondary,
        },
    });

    const trackNumSx = {
        ...NO_SPINNER_SX,
        ...focusSx,
        '& .MuiInputBase-input': {
            ...INPUT_BASE,
            fontSize: '0.75rem',
            textAlign: 'center' as const,
            color: theme.palette.text.secondary,
        },
    };

    const subArtistSx = {
        ...NO_SPINNER_SX,
        ...focusSx,
        '& .MuiInputBase-input': {
            ...INPUT_BASE,
            fontSize: '0.75rem',
            color: theme.palette.text.secondary,
        },
    };

    return (
        <Box>
            {/* Column headers */}
            <Box
                sx={{
                    display: 'grid',
                    gridTemplateColumns: gridCols,
                    gap: 1,
                    px: 2,
                    py: 0.75,
                    borderBottom: '1px solid',
                    borderColor: 'divider',
                }}
            >
                {['#', 'Title', ...(isMobile ? [] : ['Artist'])].map((h) => (
                    <Typography
                        key={h}
                        variant="caption"
                        sx={{
                            color: 'text.disabled',
                            fontSize: '0.65rem',
                            fontWeight: 600,
                            textTransform: 'uppercase',
                            letterSpacing: '0.06em',
                            textAlign: h === '#' ? 'center' : 'left',
                        }}
                    >
                        {h}
                    </Typography>
                ))}
            </Box>

            {/* Track rows */}
            {items.map((item, idx) => {
                const f = fields.get(item.id);
                if (!f) return null;
                const isVarious = f.artist !== albumArtist;

                return (
                    <Box
                        key={item.id}
                        sx={(t) => ({
                            display: 'grid',
                            gridTemplateColumns: gridCols,
                            gap: 1,
                            px: 2,
                            py: isMobile ? 1 : 0.5,
                            alignItems: 'center',
                            borderBottom:
                                idx < items.length - 1 ? '1px solid' : 'none',
                            borderColor: 'divider',
                            transition: 'background 0.1s',
                            '&:hover': {
                                background: `linear-gradient(to right, transparent, ${t.palette.primary.muted}22)`,
                            },
                        })}
                    >
                        {/* Track # */}
                        <TextField
                            variant="standard"
                            type="number"
                            value={f.track}
                            onChange={(e) =>
                                onChange(item.id, 'track', e.target.value)
                            }
                            slotProps={{
                                input: { disableUnderline: true },
                                htmlInput: { min: 1 },
                            }}
                            sx={{ ...trackNumSx, width: 28 }}
                        />

                        {/* Title (+ artist on mobile) */}
                        <Box>
                            <TextField
                                fullWidth
                                variant="standard"
                                value={f.name}
                                onChange={(e) =>
                                    onChange(item.id, 'name', e.target.value)
                                }
                                slotProps={{ input: { disableUnderline: true } }}
                                sx={FIELD_SX}
                            />
                            {isMobile && (
                                <TextField
                                    fullWidth
                                    variant="standard"
                                    value={f.artist}
                                    onChange={(e) =>
                                        onChange(item.id, 'artist', e.target.value)
                                    }
                                    slotProps={{
                                        input: { disableUnderline: true },
                                    }}
                                    sx={subArtistSx}
                                />
                            )}
                        </Box>

                        {/* Artist — desktop only */}
                        {!isMobile && (
                            <TextField
                                fullWidth
                                variant="standard"
                                value={f.artist}
                                onChange={(e) =>
                                    onChange(item.id, 'artist', e.target.value)
                                }
                                slotProps={{ input: { disableUnderline: true } }}
                                sx={artistInputSx(isVarious)}
                            />
                        )}
                    </Box>
                );
            })}
        </Box>
    );
}
