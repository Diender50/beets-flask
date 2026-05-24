import {
    Compass,
    Inbox,
    KeyRound,
    Library,
    LogOut,
    Settings,
    Users,
    UserRound,
} from 'lucide-react';
import { MouseEvent, ReactElement, useRef, useState } from 'react';
import {
    Box,
    BoxProps,
    darken,
    Divider,
    IconButton,
    ListItemIcon,
    Menu,
    MenuItem,
    Tooltip,
    Typography,
    useTheme,
} from '@mui/material';
import { styled } from '@mui/material/styles';
import Tab, { tabClasses, TabProps } from '@mui/material/Tab';
import Tabs, { tabsClasses } from '@mui/material/Tabs';
import { useQuery } from '@tanstack/react-query';
import {
    createLink,
    LinkProps,
    useNavigate,
    useRouterState,
} from '@tanstack/react-router';

import { clearToken, meQueryOptions } from '@/api/auth';
import { queryClient } from '@/api/common';

export const NAVBAR_HEIGHT = {
    desktop: '48px',
    mobile: '74px',
};

const StyledTabs = styled(Tabs)(({ theme }) => ({
    color: 'inherit',
    overflow: 'hidden',
    display: 'flex',
    width: '100%',
    justifyContent: 'center',
    [`& .${tabsClasses.indicator}`]: {
        position: 'absolute',
        top: `calc(50% - 8px)`,
        height: '16px',
        filter: 'blur(50px)',
        backgroundColor: theme.palette.secondary.main,
        zIndex: -1,
    },
    [`& .MuiTabs-scroller`]: {
        width: '100%',
        overflow: 'visible',
    },
    // Spacing of tabs for different breakpoints
    [`& .MuiTabs-flexContainer`]: {
        width: '100%',
        gap: '4px',
        justifyContent: 'center',
        [theme.breakpoints.up('laptop')]: {
            gap: '30px',
        },
    },
    [`&:hover .mouse-trail`]: {
        opacity: 1,
    },

    // Mobile grid for equal spacing
    [theme.breakpoints.down('laptop')]: {
        '& .MuiTabs-list': {
            width: 'auto',
            display: 'grid',
            gridTemplateColumns: 'repeat(var(--nav-item-count, 6), 1fr)',
            gridTemplateRows: '1fr',
            alignItems: 'center',
            justifyItems: 'center',
        },
        '& .MuiTabs-scroller': {
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
        },
        background: 'linear-gradient(to bottom, transparent, black)',
    },
}));

interface StyledTabProps
    extends Omit<LinkProps, 'children'>, Omit<TabProps, 'ref'> {
    label: string | ReactElement;
}

interface NavItemConfig {
    label: string;
    icon: ReactElement;
    to: LinkProps['to'];
}

const StyledTab = styled(createLink(Tab))<StyledTabProps>(({ theme }) => ({
    lineHeight: 'inherit',
    marginTop: 7,
    minHeight: 32,
    minWidth: 0,
    flexDirection: 'row',
    letterSpacing: '1px',
    justifyContent: 'center',
    gap: '0.5rem',
    textTransform: 'uppercase',
    overflow: 'visible',
    transition: 'color 0.3s linear',
    '& svg': {
        fontSize: 16,
        width: 16,
        height: 16,
    },
    [theme.breakpoints.up(960)]: {
        minWidth: 0,
    },
    [`& .${tabClasses.labelIcon}`]: {
        minHeight: 53,
    },
    [`& .${tabClasses.icon}`]: {
        marginBottom: 0,
    },
    [`&:hover`]: {
        color: darken(theme.palette.secondary.main, 0.2),
        transition: 'color 1s linear, text-shadow 5s ease-in',
        textShadow: `0 0 50px ${theme.palette.secondary.main}`,
    },
    [`&[data-status="active"]`]: {
        color: theme.palette.secondary.main,
    },

    //Mobile styles
    [theme.breakpoints.down('laptop')]: {
        marginTop: 0,
        height: NAVBAR_HEIGHT.mobile,
        display: 'flex',
        flexDirection: 'column',

        '& svg': {
            fontSize: 16,
            width: theme.iconSize.lg,
            height: theme.iconSize.lg,
        },
    },
}));

const TabLabel = styled(Typography)(({ theme }) => ({
    marginLeft: 8,
    lineHeight: '12px',
    [theme.breakpoints.down('laptop')]: {
        marginLeft: 0,
        fontSize: theme.typography.caption.fontSize,
        lineHeight: 'inherit',
        textAlign: 'center',
        width: '100%',
    },
}));

function NavItem({ label, ...props }: StyledTabProps) {
    return (
        // @ts-expect-error: WTF is happening here. MUI-Update broke typing!
        <StyledTab
            label={<TabLabel>{label}</TabLabel>}
            disableRipple
            {...props}
        />
    );
}

function NavTabs() {
    const location = useRouterState({ select: (s) => s.location });
    let basePath = location.pathname.split('/')[1];
    const navItems: NavItemConfig[] = [
        { label: 'Inbox', icon: <Inbox />, to: '/inbox' },
        { label: 'Library', icon: <Library />, to: '/library/browse' },
        { label: 'Artists', icon: <Users />, to: '/library/browse/artists' },
        { label: 'Discover', icon: <Compass />, to: '/library/discovery' },
    ];

    // only needed temporarily until search gets an icon in the toolbar!
    if (basePath === 'library') {
        const sub = location.pathname.split('/')[2];
        const subsub = location.pathname.split('/')[3];
        if (sub === 'browse' && subsub === 'artists') {
            basePath = 'library/browse/artists';
        } else {
            basePath += '/' + sub;
        }
    }

    const currentIdx = navItems.findIndex((item) => item.to === '/' + basePath);
    const ref = useRef<HTMLDivElement>(null);

    const handleMouseMove = (e: MouseEvent) => {
        ref.current?.style.setProperty('--mouse-x', `${e.clientX}px`);
        ref.current?.style.setProperty('--mouse-y', `${e.clientY}px`);
    };

    return (
        <StyledTabs
            ref={ref}
            value={currentIdx === -1 ? false : currentIdx}
            onMouseMove={handleMouseMove}
            sx={{ '--nav-item-count': navItems.length }}
        >
            {navItems.map((item) => (
                <NavItem key={item.to} {...item} />
            ))}
            {/* Mouse hover effect */}
            <MouseTrail />
        </StyledTabs>
    );
}

function UserMenu() {
    const navigate = useNavigate();
    const { data: user } = useQuery(meQueryOptions());
    const [anchor, setAnchor] = useState<HTMLElement | null>(null);

    function handleLogout() {
        clearToken();
        void queryClient.clear();
        void navigate({ to: '/login' });
    }

    return (
        <>
            <Tooltip title={user?.username ?? 'Account'}>
                <IconButton
                    size="small"
                    onClick={(e) => setAnchor(e.currentTarget)}
                    sx={{ ml: 'auto', mr: 1 }}
                >
                    <UserRound size={18} />
                </IconButton>
            </Tooltip>
            <Menu
                anchorEl={anchor}
                open={Boolean(anchor)}
                onClose={() => setAnchor(null)}
                transformOrigin={{ horizontal: 'right', vertical: 'top' }}
                anchorOrigin={{ horizontal: 'right', vertical: 'bottom' }}
            >
                <MenuItem disabled sx={{ opacity: '1 !important' }}>
                    <Typography variant="caption" color="text.secondary">
                        {user?.username}
                    </Typography>
                </MenuItem>
                <Divider />
                <MenuItem
                    onClick={() => {
                        setAnchor(null);
                        void navigate({ to: '/account/change-password' });
                    }}
                >
                    <ListItemIcon>
                        <KeyRound size={16} />
                    </ListItemIcon>
                    Change password
                </MenuItem>
                {user?.is_admin && (
                    <MenuItem
                        onClick={() => {
                            setAnchor(null);
                            void navigate({ to: '/admin' });
                        }}
                    >
                        <ListItemIcon>
                            <Settings size={16} />
                        </ListItemIcon>
                        Admin
                    </MenuItem>
                )}
                <Divider />
                <MenuItem onClick={handleLogout}>
                    <ListItemIcon>
                        <LogOut size={16} />
                    </ListItemIcon>
                    Sign out
                </MenuItem>
            </Menu>
        </>
    );
}

/** Navbar component
 *
 * on desktop: fixed to the top
 * on mobile: fixed to the bottom
 */
export default function NavBar(props: BoxProps) {
    return (
        <Box
            sx={(theme) => ({
                position: 'fixed',
                bottom: 0,
                zIndex: 10,
                width: '100dvw',
                height: NAVBAR_HEIGHT.mobile,
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'flex-start',
                backdropFilter: 'blur(25px)',
                //backgroundColor: "#21252933",

                [theme.breakpoints.up('laptop')]: {
                    top: 0,
                    borderBottom: '1px solid',
                    borderColor: 'divider',
                    height: NAVBAR_HEIGHT.desktop,
                    alignItems: 'center',
                },
            })}
            {...props}
        >
            <NavTabs />
            <Box
                sx={(theme) => ({
                    [theme.breakpoints.down('laptop')]: { display: 'none' },
                })}
            >
                <UserMenu />
            </Box>
        </Box>
    );
}

// Weird workaround for mui problems in console as it parses props to its children
const MouseTrail = () => {
    return (
        <Box
            className="mouse-trail"
            sx={(theme) => ({
                top: 'var(--mouse-y)',
                left: 'var(--mouse-x)',
                width: '10px',
                height: '10px',
                backgroundColor: theme.palette.secondary.main,
                filter: 'blur(25px)',
                pointerEvents: 'none',
                transition: 'opacity 0.3s ease-in-out',
                transform: 'translate(-50%, -50%)',
                position: 'absolute',
                opacity: 0,
                zIndex: -1,
            })}
        />
    );
};
