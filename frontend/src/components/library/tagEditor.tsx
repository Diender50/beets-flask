/**
 * Album tag editor — fetches album+items on open, two-tab modal:
 *   Album  : property/value list (title, artist, year, genre, label)
 *   Tracks : inline-editable track rows (matching album.tsx Tracklist style)
 *
 * Save button is wired to a TODO stub; backend endpoint not yet implemented.
 */
import { ArrowRightIcon, PlusIcon, XIcon } from 'lucide-react';
import { Suspense, useCallback, useRef, useState } from 'react';
import { PencilIcon } from 'lucide-react';
import {
    Box,
    Button,
    Chip,
    CircularProgress,
    DialogActions,
    DialogContent,
    Divider,
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
    albumartists: string[];
    year: string;
    genre: string;
    label: string;
}

interface TrackFields {
    id: number;
    name: string;
    artists: string[];
    track: string;
}

// ── Diff types + helpers ──────────────────────────────────────────────────────

interface FieldChange { label: string; before: string; after: string }
interface TrackChange { trackNum: string; trackName: string; changes: FieldChange[] }
interface TagDiff { albumChanges: FieldChange[]; trackChanges: TrackChange[] }

const joinArtists = (a: string[]) => a.filter(Boolean).join(', ') || '—';

function computeDiff(
    origAlbum: AlbumFields,
    curAlbum: AlbumFields,
    origTracks: Map<number, TrackFields>,
    curTracks: Map<number, TrackFields>,
    sortedItems: { id: number }[]
): TagDiff {
    const albumChanges: FieldChange[] = [];
    for (const { key, label } of ALBUM_FIELD_DEFS) {
        const a = origAlbum[key];
        const b = curAlbum[key];
        const changed = Array.isArray(a) && Array.isArray(b)
            ? JSON.stringify(a) !== JSON.stringify(b)
            : a !== b;
        if (changed)
            albumChanges.push({
                label,
                before: Array.isArray(a) ? joinArtists(a as string[]) : (a as string),
                after:  Array.isArray(b) ? joinArtists(b as string[]) : (b as string),
            });
    }

    const trackChanges: TrackChange[] = [];
    for (const { id } of sortedItems) {
        const orig = origTracks.get(id);
        const cur = curTracks.get(id);
        if (!orig || !cur) continue;
        const changes: FieldChange[] = [];
        if (orig.track !== cur.track)
            changes.push({ label: '#', before: orig.track, after: cur.track });
        if (orig.name !== cur.name)
            changes.push({ label: 'Title', before: orig.name, after: cur.name });
        if (JSON.stringify(orig.artists) !== JSON.stringify(cur.artists))
            changes.push({ label: 'Artist', before: joinArtists(orig.artists), after: joinArtists(cur.artists) });
        if (changes.length)
            trackChanges.push({ trackNum: cur.track, trackName: cur.name, changes });
    }

    return { albumChanges, trackChanges };
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

export function AlbumEditButton({ albumId, disabled }: { albumId: number; disabled?: boolean }) {
    const [open, setOpen] = useState(false);

    return (
        <>
            <Tooltip title={disabled ? 'Retag permission required' : 'Edit tags'}>
                <span>
                <IconButton
                    size="small"
                    disabled={disabled}
                    onClick={(e) => {
                        e.stopPropagation();
                        setOpen(true);
                    }}
                    sx={{ opacity: disabled ? 0.3 : 0.5, '&:hover': { opacity: disabled ? 0.3 : 1 }, padding: 0.5 }}
                    aria-label="Edit album tags"
                >
                    <PencilIcon size={14} />
                </IconButton>
                </span>
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
    const [confirmOpen, setConfirmOpen] = useState(false);

    const initAlbumFields = (): AlbumFields => ({
        album: expanded.name ?? '',
        albumartists: expanded.albumartists?.length
            ? expanded.albumartists
            : [expanded.albumartist ?? ''],
        year: String(expanded.year ?? ''),
        genre: expanded.genre ?? '',
        label: expanded.label ?? '',
    });

    const initTrackFields = (): Map<number, TrackFields> =>
        new Map(
            items.map((item) => [
                item.id,
                {
                    id: item.id,
                    name: item.name ?? '',
                    artists: item.artists?.length
                        ? item.artists
                        : [item.artist ?? ''],
                    track: String(item.track ?? ''),
                },
            ])
        );

    // Snapshot of original values — never mutated after mount
    const originalAlbum = useRef<AlbumFields>(initAlbumFields());
    const originalTracks = useRef<Map<number, TrackFields>>(initTrackFields());

    const [albumFields, setAlbumFields] = useState<AlbumFields>(initAlbumFields);
    const [trackFields, setTrackFields] = useState<Map<number, TrackFields>>(initTrackFields);

    const sortedItems = [...items].sort(
        (a, b) => (a.track ?? 0) - (b.track ?? 0)
    );

    const queryClient = useQueryClient();

    const saveMutation = useMutation({
        mutationFn: () =>
            updateAlbumTags(albumId, {
                album: albumFields.album || undefined,
                albumartists: albumFields.albumartists.filter(Boolean),
                year: albumFields.year ? Number(albumFields.year) : undefined,
                genre: albumFields.genre || undefined,
                label: albumFields.label || undefined,
                tracks: [...trackFields.values()].map((f) => ({
                    id: f.id,
                    name: f.name || undefined,
                    artists: f.artists.filter(Boolean),
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

    const handleSave = () => {
        const diff = computeDiff(
            originalAlbum.current,
            albumFields,
            originalTracks.current,
            trackFields,
            sortedItems
        );
        if (diff.albumChanges.length === 0 && diff.trackChanges.length === 0) {
            onClose(); // nothing changed
            return;
        }
        setConfirmOpen(true);
    };

    const diff = confirmOpen
        ? computeDiff(
              originalAlbum.current,
              albumFields,
              originalTracks.current,
              trackFields,
              sortedItems
          )
        : null;

    return (
        <>
        <Dialog
            open={open}
            onClose={(_, reason) => {
                if (reason !== 'backdropClick') onClose();
            }}
            title={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
                    {expanded.name}
                    <Chip
                        label="EXPERIMENTAL"
                        size="small"
                        color="warning"
                        variant="outlined"
                        sx={{ fontSize: '0.65rem', height: 20, fontWeight: 700, letterSpacing: '0.05em', '& .MuiChip-label': { px: 0.75 } }}
                    />
                </Box>
            }
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

        {/* Confirmation dialog */}
        {diff && (
            <ConfirmDialog
                open={confirmOpen}
                diff={diff}
                isPending={saveMutation.isPending}
                error={saveMutation.isError ? (saveMutation.error as Error).message : null}
                onConfirm={() => saveMutation.mutate()}
                onCancel={() => setConfirmOpen(false)}
            />
        )}
    </>
    );
}

// ── Confirmation dialog ───────────────────────────────────────────────────────

function ConfirmDialog({
    open,
    diff,
    isPending,
    error,
    onConfirm,
    onCancel,
}: {
    open: boolean;
    diff: TagDiff;
    isPending: boolean;
    error: string | null;
    onConfirm: () => void;
    onCancel: () => void;
}) {
    const hasAlbum = diff.albumChanges.length > 0;
    const hasTracks = diff.trackChanges.length > 0;
    const needsMove =
        diff.albumChanges.some((c) => c.label === 'Album' || c.label === 'Album artist');

    return (
        <Dialog
            open={open}
            onClose={(_, reason) => {
                if (reason !== 'backdropClick') onCancel();
            }}
            title="Confirm changes"
        >
            <DialogContent sx={{ p: 0, overflow: 'auto', minWidth: 340 }}>
                {hasAlbum && (
                    <Box sx={{ px: 2, pt: 2, pb: hasTracks ? 1 : 2 }}>
                        <Typography
                            variant="caption"
                            sx={{
                                color: 'text.disabled',
                                textTransform: 'uppercase',
                                letterSpacing: '0.06em',
                                fontSize: '0.65rem',
                                fontWeight: 600,
                            }}
                        >
                            Album
                        </Typography>
                        <Box sx={{ mt: 0.75 }}>
                            {diff.albumChanges.map((c) => (
                                <ChangeLine key={c.label} change={c} />
                            ))}
                        </Box>
                    </Box>
                )}

                {hasAlbum && hasTracks && (
                    <Divider variant="middle" sx={{ my: 0.5 }} />
                )}

                {hasTracks && (
                    <Box sx={{ px: 2, pt: hasAlbum ? 1 : 2, pb: 2 }}>
                        <Typography
                            variant="caption"
                            sx={{
                                color: 'text.disabled',
                                textTransform: 'uppercase',
                                letterSpacing: '0.06em',
                                fontSize: '0.65rem',
                                fontWeight: 600,
                            }}
                        >
                            Tracks
                        </Typography>
                        <Box sx={{ mt: 0.75, display: 'flex', flexDirection: 'column', gap: 1.25 }}>
                            {diff.trackChanges.map((tc) => (
                                <Box key={tc.trackNum + tc.trackName}>
                                    <Typography
                                        variant="body2"
                                        sx={{ fontWeight: 600, mb: 0.25 }}
                                    >
                                        {tc.trackNum}. {tc.trackName}
                                    </Typography>
                                    {tc.changes.map((c) => (
                                        <ChangeLine key={c.label} change={c} indent />
                                    ))}
                                </Box>
                            ))}
                        </Box>
                    </Box>
                )}

                {needsMove && (
                    <Box sx={{ px: 2, pb: 2 }}>
                        <Chip
                            size="small"
                            label="Files will be moved on disk"
                            color="warning"
                            variant="outlined"
                            sx={{ fontSize: '0.7rem' }}
                        />
                    </Box>
                )}
            </DialogContent>

            <DialogActions sx={{ px: 2, pb: 2, gap: 1 }}>
                {error && (
                    <Typography variant="caption" color="error" sx={{ flex: 1 }}>
                        {error}
                    </Typography>
                )}
                <Button onClick={onCancel} color="inherit" size="small" disabled={isPending}>
                    Back
                </Button>
                <Button
                    variant="contained"
                    size="small"
                    onClick={onConfirm}
                    disabled={isPending}
                    startIcon={isPending ? <CircularProgress size={12} color="inherit" /> : undefined}
                >
                    {isPending ? 'Saving…' : 'Confirm'}
                </Button>
            </DialogActions>
        </Dialog>
    );
}

function ChangeLine({ change, indent = false }: { change: FieldChange; indent?: boolean }) {
    return (
        <Box
            sx={{
                display: 'grid',
                gridTemplateColumns: indent ? '60px 1fr' : '80px 1fr',
                gap: 1,
                alignItems: 'baseline',
                py: 0.3,
            }}
        >
            <Typography
                variant="caption"
                sx={{
                    color: 'text.disabled',
                    fontSize: '0.65rem',
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                }}
            >
                {change.label}
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap' }}>
                <Typography
                    variant="body2"
                    sx={{
                        color: 'text.secondary',
                        textDecoration: 'line-through',
                        fontSize: '0.8rem',
                    }}
                >
                    {change.before || '—'}
                </Typography>
                <ArrowRightIcon size={12} style={{ flexShrink: 0, opacity: 0.5 }} />
                <Typography
                    variant="body2"
                    sx={{ color: 'text.primary', fontWeight: 600, fontSize: '0.8rem' }}
                >
                    {change.after || '—'}
                </Typography>
            </Box>
        </Box>
    );
}

// ── Album fields panel ────────────────────────────────────────────────────────

const ALBUM_FIELD_DEFS = [
    { key: 'album',        label: 'Album',        type: 'text'   },
    { key: 'albumartists', label: 'Album artists', type: 'list'   },
    { key: 'year',         label: 'Year',          type: 'number' },
    { key: 'genre',        label: 'Genre',         type: 'text'   },
    { key: 'label',        label: 'Label',         type: 'text'   },
] as const;

function AlbumFieldsPanel({
    fields,
    onChange,
}: {
    fields: AlbumFields;
    onChange: <K extends keyof AlbumFields>(field: K, value: AlbumFields[K]) => void;
}) {
    const isMobile = useMediaQuery((theme) => theme.breakpoints.down('tablet'));

    const labelSx = {
        width: isMobile ? 'auto' : 108,
        flexShrink: 0,
        color: 'text.disabled',
        textTransform: 'uppercase' as const,
        letterSpacing: '0.06em',
        fontSize: '0.65rem',
        fontWeight: 600,
    };

    const rowSx = (last: boolean) => ({
        display: 'flex',
        flexDirection: isMobile ? ('column' as const) : ('row' as const),
        alignItems: isMobile ? ('flex-start' as const) : ('center' as const),
        py: isMobile ? 1.25 : 1,
        gap: isMobile ? 0.25 : 2,
        borderBottom: last ? 'none' : '1px solid',
        borderColor: 'divider',
    });

    return (
        <Box sx={{ px: 2, py: 1 }}>
            {ALBUM_FIELD_DEFS.map(({ key, label, type }, i) => {
                const isLast = i === ALBUM_FIELD_DEFS.length - 1;
                return (
                    <Box key={key} sx={rowSx(isLast)}>
                        <Typography variant="caption" sx={labelSx}>
                            {label}
                        </Typography>
                        {type === 'list' ? (
                            <MultiValueField
                                values={fields[key] as string[]}
                                onChange={(v) => onChange(key, v as AlbumFields[typeof key])}
                            />
                        ) : (
                            <TextField
                                fullWidth
                                variant="standard"
                                type={type}
                                value={fields[key] as string}
                                onChange={(e) => onChange(key, e.target.value as AlbumFields[typeof key])}
                                size="small"
                                slotProps={{ input: { disableUnderline: true } }}
                                sx={FIELD_SX}
                            />
                        )}
                    </Box>
                );
            })}
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

    // Remove unused vars
    void artistInputSx;
    void subArtistSx;

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
                {['#', 'Title', ...(isMobile ? [] : ['Artists'])].map((h) => (
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
                const isVarious = joinArtists(f.artists) !== albumArtist;

                return (
                    <Box
                        key={item.id}
                        sx={(t) => ({
                            display: 'grid',
                            gridTemplateColumns: gridCols,
                            gap: 1,
                            px: 2,
                            py: isMobile ? 1 : 0.5,
                            alignItems: 'start',
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
                            sx={{ ...trackNumSx, width: 28, mt: 0.5 }}
                        />

                        {/* Title */}
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
                                <MultiValueField
                                    values={f.artists}
                                    onChange={(v) => onChange(item.id, 'artists', v)}
                                    dimmed={!isVarious}
                                    compact
                                />
                            )}
                        </Box>

                        {/* Artists — desktop only */}
                        {!isMobile && (
                            <MultiValueField
                                values={f.artists}
                                onChange={(v) => onChange(item.id, 'artists', v)}
                                dimmed={!isVarious}
                            />
                        )}
                    </Box>
                );
            })}
        </Box>
    );
}

// ── Multi-value field (artists list) ──────────────────────────────────────────

function MultiValueField({
    values,
    onChange,
    dimmed = false,
    compact = false,
}: {
    values: string[];
    onChange: (values: string[]) => void;
    dimmed?: boolean;
    compact?: boolean;
}) {
    const update = (i: number, val: string) => {
        const next = [...values];
        next[i] = val;
        onChange(next);
    };
    const remove = (i: number) => onChange(values.filter((_, idx) => idx !== i));
    const add = () => onChange([...values, '']);

    const entrySx = {
        ...NO_SPINNER_SX,
        '& .MuiInputBase-input': {
            ...INPUT_BASE,
            fontSize: compact ? '0.75rem' : '0.875rem',
            color: dimmed ? 'text.secondary' : 'text.primary',
        },
        '& .MuiInputBase-root:hover .MuiInputBase-input': {
            background: 'rgba(255,255,255,0.07)',
        },
        '& .Mui-focused .MuiInputBase-input': {
            background: 'rgba(255,255,255,0.08)',
            outline: '1px solid rgba(255,255,255,0.12)',
        },
    };

    return (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.25 }}>
            {values.map((val, i) => (
                <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 0.25 }}>
                    <TextField
                        fullWidth
                        variant="standard"
                        value={val}
                        onChange={(e) => update(i, e.target.value)}
                        slotProps={{ input: { disableUnderline: true } }}
                        sx={entrySx}
                    />
                    {values.length > 1 && (
                        <IconButton
                            size="small"
                            onClick={() => remove(i)}
                            tabIndex={-1}
                            sx={{ opacity: 0.3, '&:hover': { opacity: 1 }, p: 0.25, flexShrink: 0 }}
                        >
                            <XIcon size={11} />
                        </IconButton>
                    )}
                </Box>
            ))}
            <Button
                size="small"
                onClick={add}
                startIcon={<PlusIcon size={10} />}
                sx={{
                    alignSelf: 'flex-start',
                    fontSize: '0.65rem',
                    color: 'text.disabled',
                    py: 0.1,
                    px: 0.5,
                    minWidth: 0,
                    '&:hover': { color: 'text.secondary' },
                }}
            >
                Add
            </Button>
        </Box>
    );
}
