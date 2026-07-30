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
import { CSSProperties, useEffect, useRef, useState } from 'react';
import { css } from '@emotion/react';
import { SafeMarkdown } from '@superset-ui/core/components';
import { chat } from 'src/core/chat';
import {
  createConversation,
  listMessages,
  streamCompletion,
} from './copilotClient';
import {
  copilotStore,
  rowsToBubbles,
  useCopilotStore,
  type Bubble,
} from './copilotStore';

// Tight markdown spacing so lists/paragraphs read well inside a chat bubble.
const markdownCss = css`
  & > :first-of-type {
    margin-top: 0;
  }
  & > :last-child {
    margin-bottom: 0;
  }
  p {
    margin: 0.4em 0;
  }
  ul,
  ol {
    margin: 0.4em 0;
    padding-left: 1.2em;
  }
  li {
    margin: 0.15em 0;
  }
  h1,
  h2,
  h3,
  h4 {
    margin: 0.5em 0 0.3em;
    font-size: 1em;
  }
  code {
    background: rgba(0, 0, 0, 0.06);
    padding: 0 3px;
    border-radius: 3px;
    font-size: 0.9em;
  }
  pre {
    background: rgba(0, 0, 0, 0.06);
    padding: 8px;
    border-radius: 6px;
    overflow-x: auto;
  }
  pre code {
    background: none;
    padding: 0;
  }
  a {
    color: #20a7c9;
  }
`;

export default function ChatPanel() {
  const [mode, setMode] = useState(chat.getDisplayMode());
  const { convId, messages } = useCopilotStore();
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const { dispose } = chat.onDidChangeDisplayMode(m => setMode(m));
    return dispose;
  }, []);

  // Boot once per session: rehydrate the store from persisted history, or create
  // a fresh conversation. Guarded so a mode-switch remount does NOT reset state.
  useEffect(() => {
    if (copilotStore.getState().booted) return;
    copilotStore.markBooted();
    const boot = async () => {
      const stored = localStorage.getItem('copilot.convId');
      if (stored) {
        try {
          const rows = await listMessages(stored);
          copilotStore.setConvId(stored);
          copilotStore.replaceMessages(rowsToBubbles(rows));
          return;
        } catch {
          // stale / deleted conversation — fall through to create a new one
        }
      }
      try {
        const c = await createConversation('DEFAULT');
        localStorage.setItem('copilot.convId', c.id);
        copilotStore.setConvId(c.id);
      } catch (e) {
        setErr(`Cannot reach the copilot backend. ${(e as Error).message}`);
      }
    };
    boot();
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  const updateLast = (fn: (b: Bubble) => Bubble) =>
    copilotStore.setMessages(ms =>
      ms.map((m, i) => (i === ms.length - 1 ? fn(m) : m)),
    );

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    setBusy(true);
    setErr(null);
    copilotStore.setMessages(ms => [
      ...ms,
      { role: 'user', content: text },
      { role: 'assistant', content: '', streaming: true, thoughts: [] },
    ]);

    const streamOnce = async (cid: string): Promise<string | null> => {
      let failure: string | null = null;
      await streamCompletion(cid, text, {
        onToken: t => updateLast(b => ({ ...b, content: b.content + t })),
        onToolCall: (name, args) =>
          updateLast(b => ({
            ...b,
            thoughts: [
              ...(b.thoughts || []),
              `→ ${name}(${JSON.stringify(args)})`,
            ],
          })),
        onToolResult: content =>
          updateLast(b => ({
            ...b,
            thoughts: [...(b.thoughts || []), `← ${content.slice(0, 120)}`],
          })),
        onFinal: content => updateLast(b => (b.content ? b : { ...b, content })),
        onError: m => {
          failure = m;
        },
      });
      return failure;
    };

    let cid = convId;
    if (!cid) {
      try {
        const c = await createConversation('DEFAULT');
        cid = c.id;
        localStorage.setItem('copilot.convId', c.id);
        copilotStore.setConvId(c.id);
      } catch (e) {
        setErr(`Cannot reach the copilot backend. ${(e as Error).message}`);
      }
    }

    let failure = cid ? await streamOnce(cid) : 'no conversation';
    // Backend restarted → the conversation is gone (404). Recreate + retry once.
    if (failure && failure.includes('404')) {
      try {
        const c = await createConversation('DEFAULT');
        localStorage.setItem('copilot.convId', c.id);
        copilotStore.setConvId(c.id);
        updateLast(b => ({ ...b, content: '', thoughts: [] }));
        failure = await streamOnce(c.id);
      } catch (e) {
        failure = `Cannot reach the copilot backend. ${(e as Error).message}`;
      }
    }
    if (failure) setErr(failure);
    updateLast(b => ({ ...b, streaming: false }));
    setBusy(false);
  };

  return (
    <div style={{ ...styles.root, height: mode === 'panel' ? '100%' : '70vh' }}>
      <div style={styles.header}>
        <strong>Copilot</strong>
        <button
          type="button"
          style={styles.linkBtn}
          onClick={() =>
            chat.setDisplayMode(mode === 'panel' ? 'floating' : 'panel')
          }
        >
          {mode === 'panel' ? 'Float' : 'Dock'}
        </button>
      </div>

      <div ref={scrollRef} style={styles.scroll}>
        {messages.length === 0 && (
          <div style={styles.empty}>Ask me anything about your data.</div>
        )}
        {messages.map((m, i) => (
          <div
            // eslint-disable-next-line react/no-array-index-key
            key={i}
            style={{
              ...styles.row,
              justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start',
            }}
          >
            <div>
              {m.thoughts && m.thoughts.length > 0 && (
                <div style={styles.thoughts}>
                  {m.thoughts.map((t, j) => (
                    // eslint-disable-next-line react/no-array-index-key
                    <div key={j}>{t}</div>
                  ))}
                </div>
              )}
              <div
                style={{
                  ...styles.bubble,
                  ...(m.role === 'user'
                    ? styles.userBubble
                    : styles.assistantBubble),
                }}
              >
                {m.role === 'assistant' ? (
                  m.content ? (
                    <div css={markdownCss}>
                      <SafeMarkdown source={m.content} />
                    </div>
                  ) : (
                    m.streaming && '…'
                  )
                ) : (
                  m.content
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {err && <div style={styles.error}>{err}</div>}

      <div style={styles.inputRow}>
        <input
          style={styles.textInput}
          value={input}
          placeholder={convId ? 'Message the copilot…' : 'Connecting…'}
          disabled={!convId}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') {
              e.preventDefault();
              send();
            }
          }}
        />
        <button
          type="button"
          style={styles.sendBtn}
          onClick={send}
          disabled={!convId || busy}
        >
          {busy ? '…' : 'Send'}
        </button>
      </div>
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  root: {
    display: 'flex',
    flexDirection: 'column',
    width: '100%',
    height: '100%',
    background: '#fff',
    borderLeft: '1px solid #eee',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '10px 12px',
    borderBottom: '1px solid #eee',
  },
  linkBtn: {
    border: 'none',
    background: 'none',
    color: '#20a7c9',
    cursor: 'pointer',
    fontSize: 12,
  },
  scroll: {
    flex: 1,
    overflowY: 'auto',
    padding: 12,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  empty: { color: '#999', textAlign: 'center', marginTop: 24, fontSize: 13 },
  row: { display: 'flex' },
  bubble: {
    maxWidth: 320,
    padding: '8px 12px',
    borderRadius: 12,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    fontSize: 14,
  },
  userBubble: { background: '#20a7c9', color: '#fff', borderBottomRightRadius: 2 },
  assistantBubble: {
    background: '#f4f6f8',
    color: '#111',
    borderBottomLeftRadius: 2,
  },
  thoughts: {
    fontSize: 11,
    color: '#888',
    fontFamily: 'monospace',
    marginBottom: 4,
    paddingLeft: 4,
  },
  error: { color: '#e04355', fontSize: 12, padding: '4px 12px' },
  inputRow: {
    display: 'flex',
    gap: 8,
    padding: 12,
    borderTop: '1px solid #eee',
  },
  textInput: {
    flex: 1,
    border: '1px solid #ddd',
    borderRadius: 6,
    padding: 8,
    fontSize: 14,
  },
  sendBtn: {
    padding: '8px 16px',
    background: '#20a7c9',
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
  },
};
