import { PlusIcon, Trash2Icon } from 'lucide-react';
import { useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Checkbox,
    Chip,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Divider,
    FormControlLabel,
    IconButton,
    MenuItem,
    Paper,
    Select,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableRow,
    TextField,
    Tooltip,
    Typography,
} from '@mui/material';
import {
    useMutation,
    useQuery,
    useQueryClient,
} from '@tanstack/react-query';
import { createFileRoute, redirect } from '@tanstack/react-router';

import {
    createUser,
    CreateUserPayload,
    deleteUser,
    meQueryOptions,
    updateUser,
    UpdateUserPayload,
    UserInList,
    usersQueryOptions,
} from '@/api/auth';
import { PageWrapper } from '@/components/common/page';

export const Route = createFileRoute('/admin/')({
    beforeLoad: async ({ context }) => {
        const user = await context.queryClient.fetchQuery(meQueryOptions());
        if (!user.is_admin) {
            throw redirect({ to: '/' });
        }
    },
    component: AdminPage,
});

const QUALITY_OPTIONS: UserInList['max_quality'][] = [
    'flac',
    'high_lossy',
    'med_lossy',
    'low_lossy',
];

function PermissionCell({
    label,
    checked,
    onChange,
}: {
    label: string;
    checked: boolean;
    onChange: (v: boolean) => void;
}) {
    return (
        <FormControlLabel
            label={label}
            sx={{ mr: 0 }}
            control={
                <Checkbox
                    size="small"
                    checked={checked}
                    onChange={(e) => onChange(e.target.checked)}
                />
            }
        />
    );
}

interface EditDialogProps {
    user: UserInList | null;
    onClose: () => void;
}

function EditUserDialog({ user, onClose }: EditDialogProps) {
    const qc = useQueryClient();
    const [form, setForm] = useState<UpdateUserPayload>(
        user
            ? {
                  is_active: user.is_active,
                  is_admin: user.is_admin,
                  can_auto_download: user.can_auto_download,
                  can_manual_download: user.can_manual_download,
                  can_retag: user.can_retag,
                  can_delete: user.can_delete,
                  can_add_artist: user.can_add_artist,
                  max_quality: user.max_quality,
              }
            : {}
    );
    const [newPw, setNewPw] = useState('');
    const [error, setError] = useState<string | null>(null);

    const mutation = useMutation({
        mutationFn: () => {
            const payload: UpdateUserPayload = { ...form };
            if (newPw.trim()) payload.password = newPw.trim();
            return updateUser(user!.id, payload);
        },
        onSuccess: () => {
            void qc.invalidateQueries(usersQueryOptions());
            onClose();
        },
        onError: (e) => setError(e.message),
    });

    function set<K extends keyof UpdateUserPayload>(
        key: K,
        value: UpdateUserPayload[K]
    ) {
        setForm((f) => ({ ...f, [key]: value }));
    }

    return (
        <Dialog open={Boolean(user)} onClose={onClose} maxWidth="tablet" fullWidth>
            <DialogTitle>Edit {user?.username}</DialogTitle>
            <DialogContent
                sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}
            >
                {error && <Alert severity="error">{error}</Alert>}
                <FormControlLabel
                    label="Active"
                    control={
                        <Checkbox
                            checked={form.is_active ?? true}
                            onChange={(e) => set('is_active', e.target.checked)}
                        />
                    }
                />
                <FormControlLabel
                    label="Admin"
                    control={
                        <Checkbox
                            checked={form.is_admin ?? false}
                            onChange={(e) => set('is_admin', e.target.checked)}
                        />
                    }
                />
                <Divider />
                <Typography variant="caption" color="text.secondary">
                    Permissions
                </Typography>
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                    <PermissionCell
                        label="Auto-download"
                        checked={form.can_auto_download ?? false}
                        onChange={(v) => set('can_auto_download', v)}
                    />
                    <PermissionCell
                        label="Manual download"
                        checked={form.can_manual_download ?? true}
                        onChange={(v) => set('can_manual_download', v)}
                    />
                    <PermissionCell
                        label="Retag"
                        checked={form.can_retag ?? true}
                        onChange={(v) => set('can_retag', v)}
                    />
                    <PermissionCell
                        label="Delete"
                        checked={form.can_delete ?? false}
                        onChange={(v) => set('can_delete', v)}
                    />
                    <PermissionCell
                        label="Add artist"
                        checked={form.can_add_artist ?? true}
                        onChange={(v) => set('can_add_artist', v)}
                    />
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                    <Typography variant="body2">Max quality</Typography>
                    <Select
                        size="small"
                        value={form.max_quality ?? 'flac'}
                        onChange={(e) =>
                            set(
                                'max_quality',
                                e.target.value as UserInList['max_quality']
                            )
                        }
                    >
                        {QUALITY_OPTIONS.map((q) => (
                            <MenuItem key={q} value={q}>
                                {q}
                            </MenuItem>
                        ))}
                    </Select>
                </Box>
                <Divider />
                <TextField
                    label="New password (leave empty to keep)"
                    type="password"
                    size="small"
                    value={newPw}
                    onChange={(e) => setNewPw(e.target.value)}
                />
            </DialogContent>
            <DialogActions>
                <Button onClick={onClose}>Cancel</Button>
                <Button
                    variant="contained"
                    onClick={() => mutation.mutate()}
                    disabled={mutation.isPending}
                    startIcon={
                        mutation.isPending ? (
                            <CircularProgress size={14} color="inherit" />
                        ) : null
                    }
                >
                    Save
                </Button>
            </DialogActions>
        </Dialog>
    );
}

function CreateUserDialog({
    open,
    onClose,
}: {
    open: boolean;
    onClose: () => void;
}) {
    const qc = useQueryClient();
    const [form, setForm] = useState<CreateUserPayload>({
        username: '',
        password: '',
        max_quality: 'flac',
    });
    const [error, setError] = useState<string | null>(null);

    const mutation = useMutation({
        mutationFn: () => createUser(form),
        onSuccess: () => {
            void qc.invalidateQueries(usersQueryOptions());
            onClose();
            setForm({ username: '', password: '', max_quality: 'flac' });
            setError(null);
        },
        onError: (e) => setError(e.message),
    });

    function set<K extends keyof CreateUserPayload>(
        key: K,
        value: CreateUserPayload[K]
    ) {
        setForm((f) => ({ ...f, [key]: value }));
    }

    return (
        <Dialog open={open} onClose={onClose} maxWidth="tablet" fullWidth>
            <DialogTitle>New user</DialogTitle>
            <DialogContent
                sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}
            >
                {error && <Alert severity="error">{error}</Alert>}
                <TextField
                    label="Username"
                    size="small"
                    value={form.username}
                    onChange={(e) => set('username', e.target.value)}
                    required
                />
                <TextField
                    label="Password"
                    type="password"
                    size="small"
                    value={form.password}
                    onChange={(e) => set('password', e.target.value)}
                    required
                />
                <FormControlLabel
                    label="Admin"
                    control={
                        <Checkbox
                            checked={form.is_admin ?? false}
                            onChange={(e) => set('is_admin', e.target.checked)}
                        />
                    }
                />
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                    <Typography variant="body2">Max quality</Typography>
                    <Select
                        size="small"
                        value={form.max_quality ?? 'flac'}
                        onChange={(e) =>
                            set(
                                'max_quality',
                                e.target.value as UserInList['max_quality']
                            )
                        }
                    >
                        {QUALITY_OPTIONS.map((q) => (
                            <MenuItem key={q} value={q}>
                                {q}
                            </MenuItem>
                        ))}
                    </Select>
                </Box>
            </DialogContent>
            <DialogActions>
                <Button onClick={onClose}>Cancel</Button>
                <Button
                    variant="contained"
                    onClick={() => mutation.mutate()}
                    disabled={mutation.isPending || !form.username || !form.password}
                    startIcon={
                        mutation.isPending ? (
                            <CircularProgress size={14} color="inherit" />
                        ) : null
                    }
                >
                    Create
                </Button>
            </DialogActions>
        </Dialog>
    );
}

function AdminPage() {
    const { data: users = [], isLoading } = useQuery(usersQueryOptions());
    const { data: me } = useQuery(meQueryOptions());
    const qc = useQueryClient();
    const [editUser, setEditUser] = useState<UserInList | null>(null);
    const [createOpen, setCreateOpen] = useState(false);

    const deleteMutation = useMutation({
        mutationFn: deleteUser,
        onSuccess: () => void qc.invalidateQueries(usersQueryOptions()),
    });

    return (
        <PageWrapper>
            <Paper elevation={2} sx={{ m: 2, p: 2 }}>
                <Box
                    sx={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        mb: 2,
                    }}
                >
                    <Typography variant="h6" fontWeight="bold">
                        Users
                    </Typography>
                    <Button
                        variant="contained"
                        size="small"
                        startIcon={<PlusIcon size={14} />}
                        onClick={() => setCreateOpen(true)}
                    >
                        New user
                    </Button>
                </Box>

                {isLoading ? (
                    <CircularProgress size={24} />
                ) : (
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell>Username</TableCell>
                                <TableCell>Role</TableCell>
                                <TableCell>Permissions</TableCell>
                                <TableCell>Max quality</TableCell>
                                <TableCell />
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {users.map((u) => (
                                <TableRow
                                    key={u.id}
                                    hover
                                    sx={{
                                        cursor: 'pointer',
                                        opacity: u.is_active ? 1 : 0.45,
                                    }}
                                    onClick={() => setEditUser(u)}
                                >
                                    <TableCell>
                                        <Typography variant="body2">
                                            {u.username}
                                            {u.id === me?.id && (
                                                <Typography
                                                    component="span"
                                                    variant="caption"
                                                    color="text.secondary"
                                                    sx={{ ml: 1 }}
                                                >
                                                    (you)
                                                </Typography>
                                            )}
                                        </Typography>
                                    </TableCell>
                                    <TableCell>
                                        {u.is_admin ? (
                                            <Chip
                                                label="admin"
                                                size="small"
                                                color="primary"
                                            />
                                        ) : (
                                            <Chip
                                                label="user"
                                                size="small"
                                                variant="outlined"
                                            />
                                        )}
                                    </TableCell>
                                    <TableCell>
                                        <Box
                                            sx={{
                                                display: 'flex',
                                                gap: 0.5,
                                                flexWrap: 'wrap',
                                            }}
                                        >
                                            {u.can_auto_download && (
                                                <Chip
                                                    label="auto-dl"
                                                    size="small"
                                                    variant="outlined"
                                                />
                                            )}
                                            {u.can_manual_download && (
                                                <Chip
                                                    label="download"
                                                    size="small"
                                                    variant="outlined"
                                                />
                                            )}
                                            {u.can_retag && (
                                                <Chip
                                                    label="retag"
                                                    size="small"
                                                    variant="outlined"
                                                />
                                            )}
                                            {u.can_delete && (
                                                <Chip
                                                    label="delete"
                                                    size="small"
                                                    variant="outlined"
                                                />
                                            )}
                                            {u.can_add_artist && (
                                                <Chip
                                                    label="add-artist"
                                                    size="small"
                                                    variant="outlined"
                                                />
                                            )}
                                        </Box>
                                    </TableCell>
                                    <TableCell>
                                        <Typography
                                            variant="body2"
                                            fontFamily="monospace"
                                        >
                                            {u.max_quality}
                                        </Typography>
                                    </TableCell>
                                    <TableCell
                                        onClick={(e) => e.stopPropagation()}
                                    >
                                        {u.id !== me?.id && (
                                            <Tooltip title="Deactivate">
                                                <IconButton
                                                    size="small"
                                                    color="error"
                                                    onClick={() =>
                                                        deleteMutation.mutate(
                                                            u.id
                                                        )
                                                    }
                                                >
                                                    <Trash2Icon size={14} />
                                                </IconButton>
                                            </Tooltip>
                                        )}
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </Paper>

            <EditUserDialog
                key={editUser?.id ?? 'closed'}
                user={editUser}
                onClose={() => setEditUser(null)}
            />
            <CreateUserDialog
                open={createOpen}
                onClose={() => setCreateOpen(false)}
            />
        </PageWrapper>
    );
}
