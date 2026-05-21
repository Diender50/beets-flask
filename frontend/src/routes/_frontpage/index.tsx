import { createFileRoute, redirect } from '@tanstack/react-router';

export const Route = createFileRoute('/_frontpage/')({
    beforeLoad: () => {
        throw redirect({ to: '/library/browse' });
    },
});

// Re-exported for version.tsx which imports VersionString from this module.
export function VersionString(): string {
    let v = `v${__FRONTEND_VERSION__}`;
    if (__MODE__ !== 'production') v += ` (${__MODE__})`;
    return v;
}
