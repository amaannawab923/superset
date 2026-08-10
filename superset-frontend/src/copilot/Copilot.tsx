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
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { styled } from '@apache-superset/core/theme';
import { t } from '@apache-superset/core/translation';
import ConversationList from './ConversationList';
import ChatPanel from './ChatPanel';
import ArtifactPreviewPanel from './ArtifactPreviewPanel';
import { Artifact, Conversation, ConversationGroup, ChatMessage, seedGroups, uid } from './dummyData';
import {
  BackendArtifact,
  ConversationOut,
  MessageRow,
  createConversation,
  deleteConversation,
  listConversations,
  listMessages,
  patchConversation,
  streamCompletion,
} from './copilotClient';

const Layout = styled.div`
  display: flex;
  flex-direction: column;
  height: calc(100vh - ${({ theme }) => theme.sizeUnit * 12}px);
  ${({ theme }) => `background: ${theme.colorBgContainer};`}
`;

const Row = styled.div`
  display: flex;
  flex: 1;
  min-height: 0;
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

const ErrorBanner = styled.div`
  ${({ theme }) => `
    padding: ${theme.sizeUnit * 3}px ${theme.sizeUnit * 4}px;
    background: ${theme.colorErrorBg};
    color: ${theme.colorError};
    border-bottom: 1px solid ${theme.colorErrorBorder};
    font-size: ${theme.fontSizeSM}px;
  `}
`;

const toConversation = (c: ConversationOut): Conversation => ({
  id: c.id,
  title: c.title || t('New conversation'),
  messages: [],
  updatedAt: new Date(c.last_message_at || c.created_at).getTime(),
  pinned: c.metadata_json?.pinned === true,
  archived: c.status === 'ARCHIVED',
  groupId: null,
});

const rowsToMessages = (rows: MessageRow[]): ChatMessage[] =>
  rows
    .filter(r => (r.role === 'USER' || r.role === 'ASSISTANT') && r.content)
    .map(r => ({
      id: r.id,
      role: r.role === 'USER' ? 'user' : 'assistant',
      content: r.content,
      ts: new Date(r.created_at).getTime(),
      ...(r.artifacts?.length ? { artifacts: r.artifacts as Artifact[] } : {}),
    }));

// Which list section a conversation belongs to. Move up / down reorders only
// within the same section (pinned, a group, or the ungrouped "Chats" list).
const sectionKey = (c: Conversation): string => {
  if (c.archived) return 'archived';
  if (c.pinned) return 'pinned';
  if (c.groupId) return `group:${c.groupId}`;
  return 'chats';
};

export default function Copilot() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [groups] = useState<ConversationGroup[]>(seedGroups);
  const [activeId, setActiveId] = useState<string>('');
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [previewArtifact, setPreviewArtifact] = useState<Artifact | null>(null);
  const loadedMessagesFor = useRef<Set<string>>(new Set());

  const active = useMemo(
    () =>
      conversations.find(c => c.id === activeId) ??
      conversations.find(c => !c.archived),
    [conversations, activeId],
  );

  // Boot: load real conversations from copilot-platform, or start one if the
  // user has none yet.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await listConversations();
        if (cancelled) return;
        if (rows.length === 0) {
          const c = await createConversation();
          if (cancelled) return;
          loadedMessagesFor.current.add(c.id);
          setConversations([toConversation(c)]);
          setActiveId(c.id);
        } else {
          const convs = rows.map(toConversation);
          setConversations(convs);
          setActiveId(convs[0].id);
        }
      } catch (e) {
        if (!cancelled) {
          setError(t('Cannot reach the Copilot backend. %s', (e as Error).message));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Lazily load a conversation's message history the first time it's opened.
  useEffect(() => {
    if (!activeId || loadedMessagesFor.current.has(activeId)) return;
    loadedMessagesFor.current.add(activeId);
    (async () => {
      try {
        const rows = await listMessages(activeId);
        setConversations(prev =>
          prev.map(c => (c.id === activeId ? { ...c, messages: rowsToMessages(rows) } : c)),
        );
      } catch (e) {
        setError(t('Could not load this conversation. %s', (e as Error).message));
      }
    })();
  }, [activeId]);

  const handleNew = useCallback(async () => {
    try {
      const c = await createConversation();
      loadedMessagesFor.current.add(c.id);
      setConversations(prev => [toConversation(c), ...prev]);
      setActiveId(c.id);
    } catch (e) {
      setError(t('Cannot reach the Copilot backend. %s', (e as Error).message));
    }
  }, []);

  const handleSend = useCallback(
    (textValue: string) => {
      if (!active) return;
      const conversationId = active.id;
      const isFirstMessage = active.messages.length === 0;
      const userMsg: ChatMessage = {
        id: uid('m'),
        role: 'user',
        content: textValue,
        ts: Date.now(),
      };
      const assistantMsg: ChatMessage = {
        id: uid('m'),
        role: 'assistant',
        content: '',
        ts: Date.now(),
      };
      // Optimistic placeholder only — NOT persisted via patchConversation,
      // which would set title_source=USER server-side and permanently block
      // the real LLM-generated title (see completion.py) from ever landing.
      // The backend emits its own naive placeholder immediately, then a
      // `title` SSE event with the real one once the first reply lands; the
      // onTitle handler below applies it.
      const placeholderTitle =
        textValue.length > 40 ? `${textValue.slice(0, 40)}…` : textValue;

      setConversations(prev =>
        prev.map(c =>
          c.id === conversationId
            ? {
                ...c,
                title: isFirstMessage ? placeholderTitle : c.title,
                messages: [...c.messages, userMsg, assistantMsg],
                updatedAt: Date.now(),
              }
            : c,
        ),
      );

      setPendingId(conversationId);

      const updateAssistant = (fn: (prev: string) => string) => {
        setConversations(prev =>
          prev.map(c =>
            c.id !== conversationId
              ? c
              : {
                  ...c,
                  messages: c.messages.map(m =>
                    m.id === assistantMsg.id ? { ...m, content: fn(m.content) } : m,
                  ),
                },
          ),
        );
      };
      const appendArtifacts = (artifacts: BackendArtifact[]) => {
        setConversations(prev =>
          prev.map(c =>
            c.id !== conversationId
              ? c
              : {
                  ...c,
                  messages: c.messages.map(m =>
                    m.id === assistantMsg.id
                      ? { ...m, artifacts: [...(m.artifacts ?? []), ...(artifacts as Artifact[])] }
                      : m,
                  ),
                },
          ),
        );
      };
      const applyTitle = (title: string) => {
        if (!title) return;
        setConversations(prev =>
          prev.map(c => (c.id === conversationId ? { ...c, title } : c)),
        );
      };
      const clearPending = () =>
        setPendingId(prev => (prev === conversationId ? null : prev));

      streamCompletion(conversationId, textValue, {
        onToken: text => updateAssistant(prev => prev + text),
        onArtifacts: appendArtifacts,
        onTitle: applyTitle,
        onFinal: content => updateAssistant(prev => prev || content),
        onDone: clearPending,
        onError: message => {
          updateAssistant(() => `⚠️ ${message}`);
          clearPending();
        },
      }).catch(e => {
        updateAssistant(() => `⚠️ ${t('Cannot reach the Copilot backend.')} ${(e as Error).message}`);
        clearPending();
      });
    },
    [active],
  );

  // --- Conversation context-menu actions ---

  const patchLocal = useCallback(
    (id: string, fn: (c: Conversation) => Conversation) => {
      setConversations(prev => prev.map(c => (c.id === id ? fn(c) : c)));
    },
    [],
  );

  const handlePin = useCallback(
    (id: string) => {
      patchLocal(id, c => ({ ...c, pinned: true }));
      patchConversation(id, { pinned: true }).catch(() => {});
    },
    [patchLocal],
  );
  const handleUnpin = useCallback(
    (id: string) => {
      patchLocal(id, c => ({ ...c, pinned: false }));
      patchConversation(id, { pinned: false }).catch(() => {});
    },
    [patchLocal],
  );
  const handleRename = useCallback(
    (id: string, title: string) => {
      patchLocal(id, c => ({ ...c, title }));
      patchConversation(id, { title }).catch(() => {});
    },
    [patchLocal],
  );
  // Groups/sort order aren't backed by an API yet — client-side only, same as
  // before.
  const handleMoveToGroup = useCallback(
    (id: string, groupId: string | null) =>
      patchLocal(id, c => ({ ...c, groupId, pinned: false })),
    [patchLocal],
  );

  // A real (sendable) new conversation, titled after its source. Copying the
  // source's message history needs a backend endpoint that doesn't exist yet,
  // so the fork starts empty rather than showing messages the agent has no
  // memory of.
  const handleFork = useCallback(
    async (id: string) => {
      const src = conversations.find(c => c.id === id);
      if (!src) return;
      try {
        const c = await createConversation('DEFAULT', `${src.title} (fork)`);
        loadedMessagesFor.current.add(c.id);
        setConversations(prev => {
          const idx = prev.findIndex(p => p.id === id);
          const conv = toConversation(c);
          const next = [...prev];
          next.splice(idx + 1, 0, conv);
          return next;
        });
      } catch (e) {
        setError(t('Cannot reach the Copilot backend. %s', (e as Error).message));
      }
    },
    [conversations],
  );

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
      patchConversation(id, { status: 'ARCHIVED' }).catch(() => {});
    },
    [conversations, reselectAfterHide],
  );

  const handleDelete = useCallback(
    (id: string) => {
      const next = conversations.filter(c => c.id !== id);
      setConversations(next);
      reselectAfterHide(next, id);
      deleteConversation(id).catch(() => {});
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

  if (loading) {
    return (
      <Layout data-test="copilot-page">
        <Placeholder>{t('Loading conversations…')}</Placeholder>
      </Layout>
    );
  }

  return (
    <Layout data-test="copilot-page">
      {error && <ErrorBanner data-test="copilot-error">{error}</ErrorBanner>}
      <Row>
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
            onArtifactClick={setPreviewArtifact}
          />
        ) : (
          <Placeholder>{t('No conversation selected.')}</Placeholder>
        )}
        <ArtifactPreviewPanel
          artifact={previewArtifact}
          onClose={() => setPreviewArtifact(null)}
        />
      </Row>
    </Layout>
  );
}
