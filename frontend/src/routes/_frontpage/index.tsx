import { createFileRoute, redirect } from '@tanstack/react-router';

export const Route = createFileRoute('/_frontpage/')({
    beforeLoad: () => {
        throw redirect({ to: '/library/browse' });
    },
});
