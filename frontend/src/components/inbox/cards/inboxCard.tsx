import { createContext, useContext, useMemo } from 'react';
import {
    Box,
    Tooltip,
    Typography,
} from '@mui/material';
import { useQueries } from '@tanstack/react-query';

import {
    useInboxFolderConfig,
    useInboxFolderFrontendConfig,
} from '@/api/config';
import { walkFolder } from '@/api/inbox';
import { sessionQueryOptions } from '@/api/session';
import { InboxTypeIcon } from '@/components/common/icons';
import {
    ArchiveComponent,
    FileComponent,
    FolderComponent,
    GridWrapper,
    InboxGridHeader,
} from '@/components/inbox/fileTree';
import { Archive, Folder, Progress } from '@/pythonTypes';

import { InboxActions } from '../actions/buttons';

/** Context for easier use of inbox card related variables child
 * components.
 */
export interface InboxCardContext {
    folder: Folder;
    importedFolders: (Folder | Archive)[];

    // Configs
    folderConfig: ReturnType<typeof useInboxFolderConfig>;
    gridTemplateColumns: ReturnType<
        typeof useInboxFolderFrontendConfig
    >['gridTemplateColumns'];
    actionButtons: ReturnType<
        typeof useInboxFolderFrontendConfig
    >['actionButtons'];
}

const InboxCardContext = createContext<InboxCardContext | null>(null);

export const useInboxCardContext = () => {
    const context = useContext(InboxCardContext);
    if (!context) {
        throw new Error(
            'useInboxCardContext must be used within an InboxCardProvider'
        );
    }
    return context;
};

/** Given a folder get all subfolders
 * that have been imported (i.e. have a session with `status.progress` equal to `Progress.IMPORT_COMPLETED`).
 */
function useImportedFolders(folder: Folder) {
    const folders = useMemo(() => {
        const fs = [];
        for (const f of walkFolder(folder)) {
            if (f.type === 'file') continue; // skip files
            if (f.full_path === folder.full_path) continue; // skip the root folder
            fs.push(f);
        }
        return fs;
    }, [folder]);

    const sessions = useQueries({
        queries: folders.map((f) =>
            sessionQueryOptions({ folderHash: f.hash, folderPath: f.full_path })
        ),
    });

    const importedFolders = useMemo(() => {
        return folders.filter((f, i) => {
            const session = sessions[i];
            return session.data?.status.progress === Progress.IMPORT_COMPLETED;
        });
    }, [folders, sessions]);

    return importedFolders;
}

export function InboxCardProvider({
    folder,
    children,
}: {
    folder: Folder;
    children: React.ReactNode;
}) {
    const folderConfig = useInboxFolderConfig(folder.full_path);
    const { gridTemplateColumns, actionButtons } = useInboxFolderFrontendConfig(
        folder.full_path
    );

    const importedFolders = useImportedFolders(folder);

    return (
        <InboxCardContext.Provider
            value={{
                folder,
                importedFolders,
                folderConfig,
                gridTemplateColumns,
                actionButtons,
            }}
        >
            {children}
        </InboxCardContext.Provider>
    );
}

export function InboxCard({ folder }: { folder: Folder }) {
    return (
        <InboxCardProvider folder={folder}>
            <Box
                sx={{
                    width: '100%',
                    border: '1px solid',
                    borderColor: 'divider',
                    borderRadius: 1,
                    overflow: 'hidden',
                }}
            >
                <InboxCardHeader />
                <InboxCardContent />
                <InboxCardActions />
            </Box>
        </InboxCardProvider>
    );
}

function InboxCardHeader() {
    const { folder, folderConfig } = useInboxCardContext();

    const threshold = folderConfig.auto_threshold;

    let tooltip: string;
    switch (folderConfig.autotag) {
        case 'auto':
            tooltip =
                'Automatic tagging and import enabled. ' +
                (1 - threshold) * 100 +
                '% threshold.';
            break;
        case 'preview':
            tooltip = 'Automatic tagging enabled, but no import.';
            break;
        case 'bootleg':
            tooltip = 'Import as-is, and split albums by meta-data.';
            break;
        default:
            tooltip = 'No automatic tagging or import enabled.';
            break;
    }

    return (
        <Box
            sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1.5,
                px: 2,
                py: 1,
                borderBottom: '1px solid',
                borderColor: 'divider',
            }}
        >
            <Tooltip title={tooltip}>
                <Box sx={{ display: 'flex', opacity: 0.6, flexShrink: 0 }}>
                    <InboxTypeIcon size={16} type={folderConfig.autotag || undefined} />
                </Box>
            </Tooltip>
            <Typography
                variant="caption"
                color="text.disabled"
                sx={{
                    flex: 1,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    fontFamily: 'monospace',
                }}
            >
                {folderConfig.path}
            </Typography>
            <Typography variant="body2" fontWeight={600} sx={{ flexShrink: 0 }}>
                {folderConfig.name}
            </Typography>
        </Box>
    );
}

function InboxCardContent() {
    const {
        folder: inbox,
        folderConfig,
        gridTemplateColumns,
    } = useInboxCardContext();

    return (
        <Box sx={{ px: 1, py: 1 }}>
            <GridWrapper config={gridTemplateColumns}>
                {/* Only show inner folders */}
                <InboxGridHeader inboxFolderConfig={folderConfig} />
                {inbox.children.map((child) => {
                    if (child.type === 'directory') {
                        return (
                            <FolderComponent
                                key={child.hash}
                                folder={child as Folder}
                            />
                        );
                    }
                    if (child.type === 'archive') {
                        return (
                            <ArchiveComponent
                                key={child.hash}
                                archive={child}
                            />
                        );
                    }
                })}

                {/* files at bottom */}
                {inbox.children.map((child) => {
                    if (child.type === 'file') {
                        return (
                            <FileComponent key={child.full_path} file={child} />
                        );
                    }
                })}

                {/* If no inner folders, show a message */}
                {inbox.children.length === 0 && (
                    <Box
                        sx={{
                            gridColumn: '1 / -1',
                            textAlign: 'center',
                            color: 'secondary.muted',
                        }}
                    >
                        No folders in this inbox.
                    </Box>
                )}
            </GridWrapper>
        </Box>
    );
}

function InboxCardActions() {
    const { actionButtons } = useInboxCardContext();

    return (
        <Box sx={{ borderTop: '1px solid', borderColor: 'divider', px: 2, py: 1 }}>
            <InboxActions actionButtons={actionButtons} />
        </Box>
    );
}
