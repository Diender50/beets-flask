import {
    ChevronRight,
    InboxIcon,
    LibraryIcon,
} from 'lucide-react';
import { ReactNode } from 'react';
import {
    Avatar,
    Box,
    BoxProps,
    Divider,
    Typography,
} from '@mui/material';
import { Link } from '@tanstack/react-router';

import { LibraryStats } from '@/api/library';
import { InboxStats } from '@/pythonTypes';

import { humanizeBytes } from '../common/units/bytes';
import { humanizeDuration, relativeTime } from '../common/units/time';

const Dot = () => (
    <Box component="span" sx={{ color: 'text.disabled', mx: 0.5, userSelect: 'none' }}>·</Box>
);

export function LibraryStatsCard({ libraryStats }: { libraryStats: LibraryStats }) {
    return (
        <Box
            sx={{
                display: 'flex',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: 0.5,
                px: 1.5,
                py: 1,
                borderRadius: 1,
                border: '1px solid',
                borderColor: 'divider',
                backgroundColor: 'background.paper',
            }}
        >
            <LibraryIcon size={14} style={{ opacity: 0.5, flexShrink: 0 }} />
            <Typography variant="caption" fontWeight={600} sx={{ mr: 0.5 }}>Library</Typography>
            <Dot />
            <Typography variant="caption" color="text.secondary">{libraryStats.items} tracks</Typography>
            <Dot />
            <Typography variant="caption" color="text.secondary">{libraryStats.albums} albums</Typography>
            <Dot />
            <Typography variant="caption" color="text.secondary">{libraryStats.artists} artists</Typography>
            <Dot />
            <Typography variant="caption" color="text.secondary">{humanizeBytes(libraryStats.size)}</Typography>
            <Dot />
            <Typography variant="caption" color="text.secondary">{humanizeDuration(libraryStats.runtime)}</Typography>
            <Dot />
            <Typography variant="caption" color="text.disabled">
                imported {relativeTime(libraryStats.lastItemAdded)}
            </Typography>
        </Box>
    );
}

export function InboxStatsCard({ inboxStats }: { inboxStats: InboxStats }) {
    return (
        <Box
            component={Link}
            to="/inbox"
            sx={{
                display: 'flex',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: 0.5,
                px: 1.5,
                py: 1,
                borderRadius: 1,
                border: '1px solid',
                borderColor: 'divider',
                backgroundColor: 'background.paper',
                textDecoration: 'none',
                color: 'inherit',
                '&:hover': { borderColor: 'secondary.main', opacity: 0.9 },
                transition: 'border-color 0.2s',
            }}
        >
            <InboxIcon size={14} style={{ opacity: 0.5, flexShrink: 0 }} />
            <Typography variant="caption" fontWeight={600} sx={{ mr: 0.5 }}>{inboxStats.name}</Typography>
            <Dot />
            <Typography variant="caption" color="text.secondary">{inboxStats.nFiles} files</Typography>
            <Dot />
            <Typography variant="caption" color="text.secondary">{inboxStats.tagged_via_gui} tagged</Typography>
            <Dot />
            <Typography variant="caption" color="text.secondary">{inboxStats.imported_via_gui} imported</Typography>
            <Dot />
            <Typography variant="caption" color="text.secondary">{humanizeBytes(inboxStats.size)}</Typography>
            {inboxStats.last_created && (
                <>
                    <Dot />
                    <Typography variant="caption" color="text.disabled">
                        last activity {relativeTime(inboxStats.last_created)}
                    </Typography>
                </>
            )}
            <ChevronRight size={12} style={{ marginLeft: 'auto', opacity: 0.4, flexShrink: 0 }} />
        </Box>
    );
}

/** Top bar of the stats card, shows an icon and
 * accent line.
 *
 * Additional children can be passed to the placed
 * on the right side of the icon.
 */
export function CardHeader({
    icon,
    children,
    color = 'primary.main',
    reverse = false,
    sx,
    dividerPos = '50%',
    size = 'medium',
    ...props
}: {
    icon: ReactNode;
    children: ReactNode;
    color?: string;
    reverse?: boolean;
    dividerPos?: string;
    size?: 'small' | 'medium' | 'large';
} & BoxProps) {
    let wh = 40;
    if (size === 'small') {
        wh = 32;
    } else if (size === 'large') {
        wh = 52;
    }

    return (
        <Box
            sx={[
                {
                    position: 'relative',
                    flexGrow: 1,
                },
                // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
                ...(Array.isArray(sx) ? sx : [sx]),
            ]}
            {...props}
        >
            <Divider
                sx={{
                    position: 'absolute',
                    top: `calc(${dividerPos} -  1px)`,
                    width: '100%',
                    backgroundColor: color,
                    borderBottomWidth: 2,
                }}
            />
            <Box
                sx={{
                    paddingLeft: reverse ? 1 : 4,
                    paddingRight: reverse ? 4 : 1,
                    display: 'flex',
                    alignItems: 'flex-end',
                    justifyContent: 'space-between',
                    zIndex: 1,
                    flexDirection: reverse ? 'row-reverse' : 'row',
                }}
            >
                <Avatar
                    variant="rounded"
                    sx={{
                        width: wh,
                        height: wh,
                        backgroundColor: color,
                        '& > img': {
                            margin: 0,
                        },
                    }}
                >
                    {icon}
                </Avatar>
                {children}
            </Box>
        </Box>
    );
}

function ContentHeader({
    title,
    subtitle,
}: {
    title: string;
    subtitle: string;
}) {
    return (
        <>
            <Typography
                fontWeight={600}
                fontSize={16}
                color="grey.600"
                fontFamily="monospace"
            >
                {subtitle}
            </Typography>
            <Typography variant="h5" fontWeight={800} letterSpacing={0.5}>
                {title}
            </Typography>
        </>
    );
}

/** A single stat item on the stats card
 * @param title - The title of the stat item
 * @param icon - The icon to display next to the title
 * @param value - The value of the stat item
 */
function StatItem({
    title,
    icon,
    value,
}: {
    title: React.ReactNode;
    icon: React.ReactNode;
    value: React.ReactNode;
}) {
    return (
        <Box
            sx={{
                border: `2px solid`,
                borderRadius: 1,
                padding: 0.5,
                minWidth: '100px',
            }}
        >
            <Typography
                component="div"
                sx={{
                    fontSize: 16,
                    fontWeight: 600,
                    letterSpacing: '0.5px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 0.5,
                    color: 'grey.800',
                }}
            >
                <Box
                    sx={(theme) => ({
                        width: theme.iconSize.sm,
                        height: theme.iconSize.sm,
                        display: 'flex',
                        alignItems: 'center',
                    })}
                >
                    {icon}
                </Box>
                {title}
            </Typography>
            <Typography
                variant="h6"
                fontWeight={600}
                fontFamily="monospace"
                sx={{ paddingLeft: 1, textAlign: 'right', width: '100%' }}
            >
                {value}
            </Typography>
        </Box>
    );
}
