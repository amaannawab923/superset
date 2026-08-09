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
import { useCallback, useMemo, useState } from 'react';
import { styled } from '@apache-superset/core/theme';
import { t } from '@apache-superset/core/translation';
import ConversationList from './ConversationList';
import ChatPanel from './ChatPanel';
import {
  Conversation,
  ConversationGroup,
  ChatMessage,
  dummyReply,
  seedConversations,
  seedGroups,
  uid,
} from './dummyData';

const Layout = styled.div`
  display: flex;
  height: calc(100vh - ${({ theme }) => theme.sizeUnit * 12}px);
  ${({ theme }) => `background: ${theme.colorBgContainer};`}
`;

const Placeholder = styled.div`
  ${({ theme }) => `
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    color: ${theme.colorTextSecondary};
    font-size: ${theme.fontSize}px;
  `}
`;

// Long enough that the blinking "active" dot on the conversation is clearly
// visible while the (stubbed) reply is pending.
const REPLY_DELAY_MS = 1600;

// Which list section a conversation belongs to. Move up / down reorders only
// within the same section (pinned, a group, or the ungrouped "Chats" list).
const sectionKey = (c: Conversation): string => {
  if (c.archived) return 'archived';
  if (c.pinned) return 'pinned';
  if (c.groupId) return `group:${c.groupId}`;
  return 'chats';
};

export default function Copilot() {
  const [conversations, setConversations] = useState<Conversation[]>(seedConversations);
  const [groups] = useState<ConversationGroup[]>(seedGroups);
  const [activeId, setActiveId] = useState<string>(seedConversations[0].id);
  // Id of the conversation currently awaiting a (stubbed) reply, or null.
  const [pendingId, setPendingId] = useState<string | null>(null);

  const active = useMemo(
    () =>
      conversations.find(c => c.id === activeId) ??
      conversations.find(c => !c.archived),
    [conversations, activeId],
  );

  const appendMessage = useCallback(
    (conversationId: string, message: ChatMessage, retitle?: string) => {
      setConversations(prev =>
        prev.map(c =>
          c.id === conversationId
            ? {
                ...c,
                title:
                  retitle && (c.title === 'New conversation' || c.messages.length === 0)
                    ? retitle
                    : c.title,
                messages: [...c.messages, message],
                updatedAt: message.ts,
              }
            : c,
        ),
      );
    },
    [],
  );

  const handleNew = useCallback(() => {
    const conv: Conversation = {
      id: uid('c'),
      title: 'New conversation',
      messages: [],
      updatedAt: Date.now(),
      pinned: false,
      groupId: null,
    };
    setConversations(prev => [conv, ...prev]);
    setActiveId(conv.id);
  }, []);

  const handleSend = useCallback(
    (textValue: string) => {
      if (!active) return;
      const conversationId = active.id;
      const userMsg: ChatMessage = {
        id: uid('m'),
        role: 'user',
        content: textValue,
        ts: Date.now(),
      };
      // Use the first user message as the conversation title.
      const title = textValue.length > 40 ? `${textValue.slice(0, 40)}…` : textValue;
      appendMessage(conversationId, userMsg, title);

      setPendingId(conversationId);
      // Stubbed assistant reply — swap this timeout for the agent stream later.
      window.setTimeout(() => {
        appendMessage(conversationId, {
          id: uid('m'),
          role: 'assistant',
          content: dummyReply(textValue),
          ts: Date.now(),
        });
        setPendingId(prev => (prev === conversationId ? null : prev));
      }, REPLY_DELAY_MS);
    },
    [active, appendMessage],
  );

  // --- Conversation context-menu actions (all dummy, in-memory) ---

  const patch = useCallback(
    (id: string, fn: (c: Conversation) => Conversation) => {
      setConversations(prev => prev.map(c => (c.id === id ? fn(c) : c)));
    },
    [],
  );

  const handlePin = useCallback((id: string) => patch(id, c => ({ ...c, pinned: true })), [patch]);
  const handleUnpin = useCallback((id: string) => patch(id, c => ({ ...c, pinned: false })), [patch]);
  const handleRename = useCallback(
    (id: string, title: string) => patch(id, c => ({ ...c, title })),
    [patch],
  );
  const handleMoveToGroup = useCallback(
    (id: string, groupId: string | null) =>
      // Unpin so the chat actually surfaces under its new group section.
      patch(id, c => ({ ...c, groupId, pinned: false })),
    [patch],
  );

  const handleFork = useCallback((id: string) => {
    setConversations(prev => {
      const idx = prev.findIndex(c => c.id === id);
      if (idx < 0) return prev;
      const src = prev[idx];
      const copy: Conversation = {
        ...src,
        id: uid('c'),
        title: `${src.title} (fork)`,
        pinned: false,
        messages: src.messages.map(m => ({ ...m, id: uid('m') })),
        updatedAt: Date.now(),
      };
      const next = [...prev];
      next.splice(idx + 1, 0, copy);
      return next;
    });
  }, []);

  // When the active conversation leaves the visible list, fall back to the
  // first still-visible one.
  const reselectAfterHide = useCallback(
    (next: Conversation[], removedId: string) => {
      if (activeId !== removedId) return;
      const fallback = next.find(c => !c.archived);
      setActiveId(fallback ? fallback.id : '');
    },
    [activeId],
  );

  const handleArchive = useCallback(
    (id: string) => {
      const next = conversations.map(c => (c.id === id ? { ...c, archived: true } : c));
      setConversations(next);
      reselectAfterHide(next, id);
    },
    [conversations, reselectAfterHide],
  );

  const handleDelete = useCallback(
    (id: string) => {
      const next = conversations.filter(c => c.id !== id);
      setConversations(next);
      reselectAfterHide(next, id);
    },
    [conversations, reselectAfterHide],
  );

  const handleMove = useCallback((id: string, dir: 'up' | 'down') => {
    setConversations(prev => {
      const arr = [...prev];
      const idx = arr.findIndex(c => c.id === id);
      if (idx < 0) return prev;
      const key = sectionKey(arr[idx]);
      const step = dir === 'up' ? -1 : 1;
      let j = idx + step;
      while (j >= 0 && j < arr.length && sectionKey(arr[j]) !== key) j += step;
      if (j < 0 || j >= arr.length) return prev;
      [arr[idx], arr[j]] = [arr[j], arr[idx]];
      return arr;
    });
  }, []);

  return (
    <Layout data-test="copilot-page">
      <ConversationList
        conversations={conversations}
        groups={groups}
        activeId={active ? active.id : ''}
        pendingId={pendingId}
        onSelect={setActiveId}
        onNew={handleNew}
        onPin={handlePin}
        onUnpin={handleUnpin}
        onRename={handleRename}
        onFork={handleFork}
        onArchive={handleArchive}
        onDelete={handleDelete}
        onMove={handleMove}
        onMoveToGroup={handleMoveToGroup}
      />
      {active ? (
        <ChatPanel
          conversation={active}
          pending={pendingId === active.id}
          onSend={handleSend}
        />
      ) : (
        <Placeholder>{t('No conversation selected.')}</Placeholder>
      )}
    </Layout>
  );
}
