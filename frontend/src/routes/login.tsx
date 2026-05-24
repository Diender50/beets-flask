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
import { useQuery } from '@tanstack/react-query';
import { createFileRoute, useNavigate } from '@tanstack/react-router';

import {
    login,
    meQueryOptions,
    needsSetupQueryOptions,
    register,
    setToken,
} from '@/api/auth';
import { queryClient } from '@/api/common';

export const Route = createFileRoute('/login')({
    component: LoginPage,
});

function LoginPage() {
    const navigate = useNavigate();
    const { data: setupStatus } = useQuery(needsSetupQueryOptions());
    const isFirstRun = setupStatus?.needs_setup === true;

    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        setError(null);
        setLoading(true);
        try {
            if (isFirstRun) {
                const result = await register(username, password);
                setToken(result.token);
            } else {
                const result = await login(username, password);
                setToken(result.token);
            }
            await queryClient.invalidateQueries(meQueryOptions());
            void navigate({ to: '/' });
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : String(err));
        } finally {
            setLoading(false);
        }
    }

    return (
        <Box
            sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100dvh',
                p: 2,
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
                <Typography variant="h5" fontWeight="bold" textAlign="center">
                    {isFirstRun ? 'Create admin account' : 'Sign in'}
                </Typography>

                {isFirstRun && (
                    <Alert severity="info">
                        No accounts yet. This will create the first admin account.
                    </Alert>
                )}

                {error && <Alert severity="error">{error}</Alert>}

                <Box
                    component="form"
                    onSubmit={(e) => void handleSubmit(e)}
                    sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}
                >
                    <TextField
                        label="Username"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        autoComplete="username"
                        autoFocus
                        required
                    />
                    <TextField
                        label="Password"
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        autoComplete={
                            isFirstRun ? 'new-password' : 'current-password'
                        }
                        required
                    />
                    <Button
                        type="submit"
                        variant="contained"
                        disabled={loading}
                        startIcon={
                            loading ? (
                                <CircularProgress size={16} color="inherit" />
                            ) : null
                        }
                    >
                        {isFirstRun ? 'Create account' : 'Sign in'}
                    </Button>
                </Box>
            </Paper>
        </Box>
    );
}
