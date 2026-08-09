/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */
import { ComponentProps, KeyboardEvent, useState } from 'react';
import { styled } from '@apache-superset/core/theme';
import { t } from '@apache-superset/core/translation';
import { Button, Dropdown, Icons } from '@superset-ui/core/components';
import { Conversation, ConversationGroup } from './dummyData';

const Sidebar = styled.div`
  ${({ theme }) => `
    width: 280px;
    min-width: 280px;
    height: 100%;
    display: flex;
    flex-direction: column;
    border-right: 1px solid ${theme.colorBorderSecondary};
    background: ${theme.colorBgLayout};
  `}
`;

const Header = styled.div`
  ${({ theme }) => `
    padding: ${theme.sizeUnit * 3}px;
    border-bottom: 1px solid ${theme.colorBorderSecondary};
  `}
`;

const List = styled.div`
  flex: 1;
  overflow-y: auto;
  ${({ theme }) => `padding: ${theme.sizeUnit * 2}px;`}
`;

const SectionHeader = styled.button`
  ${({ theme }) => `
    display: flex;
    align-items: center;
    gap: ${theme.sizeUnit}px;
    width: 100%;
    border: none;
    background: transparent;
    cursor: pointer;
    color: ${theme.colorTextSecondary};
    font-size: ${theme.fontSizeSM}px;
    font-weight: ${theme.fontWeightStrong};
    text-transform: uppercase;
    letter-spacing: 0.04em;
    text-align: left;
    padding: ${theme.sizeUnit * 2}px ${theme.sizeUnit * 2}px ${theme.sizeUnit}px;
    margin-top: ${theme.sizeUnit}px;
    &:hover {
      color: ${theme.colorText};
    }
  `}
`;

// Down chevron when expanded, right chevron when collapsed (Claude Code style).
const Chevron = styled.span`
  ${({ theme }) => `
    display: inline-flex;
    align-items: center;
    color: ${theme.colorTextTertiary};
  `}
`;

const Row = styled.div<{ active: boolean }>`
  ${({ theme, active }) => `
    position: relative;
    display: flex;
    align-items: center;
    border-radius: ${theme.borderRadius}px;
    margin-bottom: ${theme.sizeUnit}px;
    background: ${active ? theme.colorPrimaryBg : 'transparent'};
    &:hover {
      background: ${active ? theme.colorPrimaryBg : theme.colorBgTextHover};
    }
    &:hover .copilot-kebab {
      opacity: 1;
    }
  `}
`;

const Main = styled.div`
  ${({ theme }) => `
    flex: 1;
    min-width: 0;
    cursor: pointer;
    padding: ${theme.sizeUnit * 2}px ${theme.sizeUnit * 3}px;
  `}
`;

const Title = styled.div`
  ${({ theme }) => `
    font-weight: ${theme.fontWeightStrong};
    font-size: ${theme.fontSizeSM}px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: ${theme.colorText};
  `}
`;

const Preview = styled.div`
  ${({ theme }) => `
    color: ${theme.colorTextSecondary};
    font-size: ${theme.fontSizeSM}px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin-top: ${theme.sizeUnit / 2}px;
  `}
`;

const RenameInput = styled.input`
  ${({ theme }) => `
    width: 100%;
    box-sizing: border-box;
    font-size: ${theme.fontSizeSM}px;
    font-weight: ${theme.fontWeightStrong};
    padding: ${theme.sizeUnit / 2}px ${theme.sizeUnit}px;
    border-radius: ${theme.borderRadius}px;
    border: 1px solid ${theme.colorPrimary};
    background: ${theme.colorBgContainer};
    color: ${theme.colorText};
    &:focus {
      outline: none;
    }
  `}
`;

const Kebab = styled.button`
  ${({ theme }) => `
    opacity: 0;
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: center;
    width: ${theme.sizeUnit * 7}px;
    height: ${theme.sizeUnit * 7}px;
    margin-right: ${theme.sizeUnit}px;
    border: none;
    background: transparent;
    border-radius: ${theme.borderRadius}px;
    cursor: pointer;
    color: ${theme.colorTextSecondary};
    &:hover {
      background: ${theme.colorBgContainer};
      color: ${theme.colorText};
    }
    &[aria-expanded='true'] {
      opacity: 1;
    }
  `}
`;

const EmptyHint = styled.div`
  ${({ theme }) => `
    color: ${theme.colorTextTertiary};
    font-size: ${theme.fontSizeSM}px;
    padding: ${theme.sizeUnit}px ${theme.sizeUnit * 3}px ${theme.sizeUnit * 2}px;
  `}
`;

// Derive the menu types from the Dropdown wrapper so we avoid importing
// antd's MenuProps directly (per the frontend modernization guidelines).
type DropdownMenu = NonNullable<ComponentProps<typeof Dropdown>['menu']>;
type MenuItems = DropdownMenu['items'];

export interface ConversationActions {
  onPin: (id: string) => void;
  onUnpin: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onFork: (id: string) => void;
  onArchive: (id: string) => void;
  onDelete: (id: string) => void;
  onMove: (id: string, dir: 'up' | 'down') => void;
  onMoveToGroup: (id: string, groupId: string | null) => void;
}

export interface ConversationListProps extends ConversationActions {
  conversations: Conversation[];
  groups: ConversationGroup[];
  activeId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
}

const GROUP_PREFIX = 'group:';
const UNGROUPED_KEY = 'group:__none';

export default function ConversationList({
  conversations,
  groups,
  activeId,
  onSelect,
  onNew,
  onPin,
  onUnpin,
  onRename,
  onFork,
  onArchive,
  onDelete,
  onMove,
  onMoveToGroup,
}: ConversationListProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  // Collapsed sections keyed by section id ('pinned', a group id, or 'chats').
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const toggleSection = (id: string) =>
    setCollapsed(prev => ({ ...prev, [id]: !prev[id] }));

  const startRename = (c: Conversation) => {
    setEditingId(c.id);
    setDraft(c.title);
  };

  const commitRename = (c: Conversation) => {
    const next = draft.trim();
    if (next && next !== c.title) {
      onRename(c.id, next);
    }
    setEditingId(null);
  };

  const onRenameKeyDown = (e: KeyboardEvent<HTMLInputElement>, c: Conversation) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitRename(c);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setEditingId(null);
    }
  };

  const buildMenu = (
    c: Conversation,
    isFirst: boolean,
    isLast: boolean,
  ): MenuItems => [
    {
      key: 'moveUp',
      label: t('Move up'),
      icon: <Icons.UpOutlined />,
      disabled: isFirst,
    },
    {
      key: 'moveDown',
      label: t('Move down'),
      icon: <Icons.DownOutlined />,
      disabled: isLast,
    },
    { type: 'divider' },
    {
      key: 'pin',
      label: t('Pin'),
      icon: <Icons.PushpinOutlined />,
      disabled: !!c.pinned,
    },
    {
      key: 'unpin',
      label: t('Unpin'),
      icon: <Icons.PushpinFilled />,
      disabled: !c.pinned,
    },
    { type: 'divider' },
    { key: 'rename', label: t('Rename'), icon: <Icons.EditOutlined /> },
    { key: 'fork', label: t('Fork'), icon: <Icons.CopyOutlined /> },
    {
      key: 'moveToGroup',
      label: t('Move to group'),
      icon: <Icons.FolderOutlined />,
      children: [
        ...groups.map(g => ({
          key: `${GROUP_PREFIX}${g.id}`,
          label: g.name,
          disabled: c.groupId === g.id,
        })),
        { type: 'divider' as const },
        {
          key: UNGROUPED_KEY,
          label: t('Ungrouped'),
          disabled: !c.groupId,
        },
      ],
    },
    { key: 'archive', label: t('Archive'), icon: <Icons.DownSquareOutlined /> },
    { type: 'divider' },
    {
      key: 'delete',
      label: t('Delete'),
      icon: <Icons.DeleteOutlined />,
      danger: true,
    },
  ];

  const handleAction = (c: Conversation, key: string) => {
    if (key.startsWith(GROUP_PREFIX)) {
      onMoveToGroup(c.id, key === UNGROUPED_KEY ? null : key.slice(GROUP_PREFIX.length));
      return;
    }
    switch (key) {
      case 'moveUp':
        onMove(c.id, 'up');
        break;
      case 'moveDown':
        onMove(c.id, 'down');
        break;
      case 'pin':
        onPin(c.id);
        break;
      case 'unpin':
        onUnpin(c.id);
        break;
      case 'rename':
        startRename(c);
        break;
      case 'fork':
        onFork(c.id);
        break;
      case 'archive':
        onArchive(c.id);
        break;
      case 'delete':
        onDelete(c.id);
        break;
      default:
        break;
    }
  };

  const renderItem = (c: Conversation, index: number, count: number) => {
    const last = c.messages[c.messages.length - 1];
    const editing = editingId === c.id;
    // The same menu backs both entry points: the kebab (left-click) and the
    // row itself (right-click / native context menu).
    const menu: DropdownMenu = {
      items: buildMenu(c, index === 0, index === count - 1),
      onClick: ({ key, domEvent }) => {
        domEvent.stopPropagation();
        handleAction(c, key);
      },
    };
    return (
      <Dropdown key={c.id} trigger={['contextMenu']} menu={menu}>
        <Row active={c.id === activeId} data-test="copilot-conversation">
          <Main onClick={() => onSelect(c.id)}>
            {editing ? (
              <RenameInput
                // eslint-disable-next-line jsx-a11y/no-autofocus
                autoFocus
                value={draft}
                onChange={e => setDraft(e.target.value)}
                onClick={e => e.stopPropagation()}
                onKeyDown={e => onRenameKeyDown(e, c)}
                onBlur={() => commitRename(c)}
                data-test="copilot-rename-input"
              />
            ) : (
              <>
                <Title>{c.title}</Title>
                <Preview>{last ? last.content : t('No messages yet')}</Preview>
              </>
            )}
          </Main>
          <Dropdown trigger={['click']} menu={menu}>
            <Kebab
              className="copilot-kebab"
              onClick={e => e.stopPropagation()}
              aria-label={t('Conversation menu')}
              data-test="copilot-conversation-menu"
            >
              <Icons.MoreOutlined />
            </Kebab>
          </Dropdown>
        </Row>
      </Dropdown>
    );
  };

  const visible = conversations.filter(c => !c.archived);
  const pinned = visible.filter(c => c.pinned);
  const chats = visible.filter(c => !c.pinned && !c.groupId);
  const archivedCount = conversations.length - visible.length;

  const renderSection = (id: string, label: string, items: Conversation[]) => {
    const isCollapsed = !!collapsed[id];
    return (
      <div key={id}>
        <SectionHeader
          type="button"
          onClick={() => toggleSection(id)}
          aria-expanded={!isCollapsed}
          data-test="copilot-section-header"
        >
          <Chevron>
            {isCollapsed ? (
              <Icons.RightOutlined iconSize="s" />
            ) : (
              <Icons.DownOutlined iconSize="s" />
            )}
          </Chevron>
          {label}
        </SectionHeader>
        {!isCollapsed &&
          (items.length === 0 ? (
            <EmptyHint>{t('No conversations')}</EmptyHint>
          ) : (
            items.map((c, i) => renderItem(c, i, items.length))
          ))}
      </div>
    );
  };

  return (
    <Sidebar>
      <Header>
        <Button
          buttonStyle="primary"
          block
          onClick={onNew}
          data-test="copilot-new-chat"
        >
          {t('New conversation')}
        </Button>
      </Header>
      <List>
        {pinned.length > 0 && renderSection('pinned', t('Pinned'), pinned)}

        {groups.map(g =>
          renderSection(
            g.id,
            g.name,
            visible.filter(c => !c.pinned && c.groupId === g.id),
          ),
        )}

        {renderSection('chats', t('Chats'), chats)}

        {archivedCount > 0 && (
          <EmptyHint data-test="copilot-archived-count">
            {t('%s archived', archivedCount)}
          </EmptyHint>
        )}
      </List>
    </Sidebar>
  );
}
