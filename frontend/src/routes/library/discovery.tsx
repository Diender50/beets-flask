import { Compass, Sparkles } from 'lucide-react';
import { Box, Chip, Divider, Typography } from '@mui/material';
import { useSuspenseQuery } from '@tanstack/react-query';
import { createFileRoute, Link } from '@tanstack/react-router';

import { artistsQueryOptions } from '@/api/library';
import { PageWrapper } from '@/components/common/page';

export const Route = createFileRoute('/library/discovery')({
    component: RouteComponent,
    loader: async ({ context }) => {
        await context.queryClient.ensureQueryData(artistsQueryOptions());
    },
});

function RouteComponent() {
    const { data: artists } = useSuspenseQuery(artistsQueryOptions());

    const topSeeds = [...artists]
        .sort((a, b) => b.item_count - a.item_count)
        .slice(0, 12);

    return (
        <PageWrapper
            title="Discovery"
            sx={(theme) => ({
                display: 'flex',
                flexDirection: 'column',
                gap: 2,
                height: '100%',
                overflow: 'auto',
                padding: 2,
                [theme.breakpoints.up('laptop')]: {
                    padding: 3,
                },
            })}
        >
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Compass size={28} />
                <Typography variant="h4" fontWeight={700}>
                    Global Artist Discovery
                </Typography>
            </Box>

            <Typography color="text.secondary">
                Phase 5.1 bootstrap: this page uses your current library profile
                to build discovery seeds. Recommendation ranking and feedback loop
                arrive in Phase 5.2.
            </Typography>

            <Divider />

            <Box
                sx={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: 1,
                }}
            >
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Sparkles size={20} />
                    <Typography variant="h6" fontWeight={700}>
                        Based on your library
                    </Typography>
                </Box>
                <Typography variant="body2" color="text.secondary">
                    {artists.length} artists available in profile
                </Typography>
            </Box>

            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                {topSeeds.length > 0 ? (
                    topSeeds.map((artist) => (
                        <Chip
                            key={artist.artist}
                            label={`${artist.artist} (${artist.item_count})`}
                            component={Link}
                            clickable
                            to="/library/browse/artists/$artist"
                            params={{ artist: artist.artist }}
                            sx={{ maxWidth: '100%' }}
                        />
                    ))
                ) : (
                    <Typography color="text.secondary">
                        No library artists found yet.
                    </Typography>
                )}
            </Box>

        </PageWrapper>
    );
}
