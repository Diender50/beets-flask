import { useState } from 'react';
import {
    Alert,
    Box,
    Button,
    CircularProgress,
    Paper,
    TextField,
    Typography,
} from '@mui/material';
import { createFileRoute, useNavigate } from '@tanstack/react-router';

import { changePassword } from '@/api/auth';
import { PageWrapper } from '@/components/common/page';

export const Route = createFileRoute('/account/change-password')({
    component: ChangePasswordPage,
});

function ChangePasswordPage() {
    const navigate = useNavigate();
    const [oldPw, setOldPw] = useState('');
    const [newPw, setNewPw] = useState('');
    const [confirm, setConfirm] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState(false);
    const [loading, setLoading] = useState(false);

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        setError(null);
        if (newPw !== confirm) {
            setError('New passwords do not match');
            return;
        }
        if (newPw.length < 6) {
            setError('New password must be at least 6 characters');
            return;
        }
        setLoading(true);
        try {
            await changePassword(oldPw, newPw);
            setSuccess(true);
            setTimeout(() => void navigate({ to: '/' }), 1500);
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        } finally {
            setLoading(false);
        }
    }

    return (
        <PageWrapper>
            <Box
                sx={{
                    display: 'flex',
                    justifyContent: 'center',
                    pt: 6,
                    px: 2,
                }}
            >
                <Paper
                    elevation={4}
                    sx={{
                        p: 4,
                        width: '100%',
                        maxWidth: 400,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 2,
                    }}
                >
                    <Typography variant="h6" fontWeight="bold">
                        Change password
                    </Typography>

                    {success && (
                        <Alert severity="success">
                            Password changed. Redirecting...
                        </Alert>
                    )}
                    {error && <Alert severity="error">{error}</Alert>}

                    <Box
                        component="form"
                        onSubmit={(e) => void handleSubmit(e)}
                        sx={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 2,
                        }}
                    >
                        <TextField
                            label="Current password"
                            type="password"
                            value={oldPw}
                            onChange={(e) => setOldPw(e.target.value)}
                            autoComplete="current-password"
                            required
                        />
                        <TextField
                            label="New password"
                            type="password"
                            value={newPw}
                            onChange={(e) => setNewPw(e.target.value)}
                            autoComplete="new-password"
                            required
                        />
                        <TextField
                            label="Confirm new password"
                            type="password"
                            value={confirm}
                            onChange={(e) => setConfirm(e.target.value)}
                            autoComplete="new-password"
                            required
                        />
                        <Button
                            type="submit"
                            variant="contained"
                            disabled={loading || success}
                            startIcon={
                                loading ? (
                                    <CircularProgress size={16} color="inherit" />
                                ) : null
                            }
                        >
                            Change password
                        </Button>
                    </Box>
                </Paper>
            </Box>
        </PageWrapper>
    );
}
