import React, { useEffect, useRef, useState } from 'react';
import { chat } from '@apache-superset/core';
import { createConversation, streamCompletion } from './copilotClient';

type Role = 'user' | 'assistant';

interface Bubble {
  role: Role;
  content: string;
  streaming?: boolean;
  thoughts?: string[]; // tool-call / tool-result timeline (A5 rows #2/#3)
}

export default function ChatPanel() {
  const [mode, setMode] = useState(chat.getDisplayMode());
  const [convId, setConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Bubble[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const { dispose } = chat.onDidChangeDisplayMode(m => setMode(m));
    return dispose;
  }, []);

  useEffect(() => {
    createConversation('DEFAULT')
      .then(c => setConvId(c.id))
      .catch(e => setErr(`Could not reach the copilot backend. ${e.message}`));
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  const updateLast = (fn: (b: Bubble) => Bubble) =>
    setMessages(ms => ms.map((m, i) => (i === ms.length - 1 ? fn(m) : m)));

  const send = async () => {
    const text = input.trim();
    if (!text || !convId || busy) return;
    setInput('');
    setBusy(true);
    setErr(null);
    setMessages(ms => [
      ...ms,
      { role: 'user', content: text },
      { role: 'assistant', content: '', streaming: true, thoughts: [] },
    ]);

    await streamCompletion(convId, text, {
      onToken: t => updateLast(b => ({ ...b, content: b.content + t })),
      onToolCall: (name, args) =>
        updateLast(b => ({
          ...b,
          thoughts: [...(b.thoughts || []), `→ ${name}(${JSON.stringify(args)})`],
        })),
      onToolResult: content =>
        updateLast(b => ({
          ...b,
          thoughts: [...(b.thoughts || []), `← ${content.slice(0, 120)}`],
        })),
      onFinal: content =>
        updateLast(b => (b.content ? b : { ...b, content })),
      onDone: () => updateLast(b => ({ ...b, streaming: false })),
      onError: message => {
        setErr(message);
        updateLast(b => ({ ...b, streaming: false }));
      },
    });
    setBusy(false);
  };

  return (
    <div style={{ ...styles.root, height: mode === 'panel' ? '100%' : '70vh' }}>
      <div style={styles.header}>
        <strong>Copilot</strong>
        <button
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
          <div key={i} style={{ ...styles.row, justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
            <div>
              {m.thoughts && m.thoughts.length > 0 && (
                <div style={styles.thoughts}>
                  {m.thoughts.map((t, j) => (
                    <div key={j}>{t}</div>
                  ))}
                </div>
              )}
              <div
                style={{
                  ...styles.bubble,
                  ...(m.role === 'user' ? styles.userBubble : styles.assistantBubble),
                }}
              >
                {m.content || (m.streaming ? '…' : '')}
              </div>
            </div>
          </div>
        ))}
      </div>

      {err && <div style={styles.error}>{err}</div>}

      <div style={styles.inputRow}>
        <textarea
          style={styles.textarea}
          rows={2}
          value={input}
          placeholder={convId ? 'Message the copilot…' : 'Connecting…'}
          disabled={!convId}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button style={styles.sendBtn} onClick={send} disabled={!convId || busy}>
          {busy ? '…' : 'Send'}
        </button>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  root: { display: 'flex', flexDirection: 'column', width: '100%', background: '#fff', border: '1px solid #eee', borderRadius: 8, overflow: 'hidden' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', borderBottom: '1px solid #eee' },
  linkBtn: { border: 'none', background: 'none', color: '#20a7c9', cursor: 'pointer', fontSize: 12 },
  scroll: { flex: 1, overflowY: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 8 },
  empty: { color: '#999', textAlign: 'center', marginTop: 24, fontSize: 13 },
  row: { display: 'flex' },
  bubble: { maxWidth: 420, padding: '8px 12px', borderRadius: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 14 },
  userBubble: { background: '#20a7c9', color: '#fff', borderBottomRightRadius: 2 },
  assistantBubble: { background: '#f4f6f8', color: '#111', borderBottomLeftRadius: 2 },
  thoughts: { fontSize: 11, color: '#888', fontFamily: 'monospace', marginBottom: 4, paddingLeft: 4 },
  error: { color: '#e04355', fontSize: 12, padding: '4px 12px' },
  inputRow: { display: 'flex', gap: 8, padding: 12, borderTop: '1px solid #eee' },
  textarea: { flex: 1, resize: 'none', border: '1px solid #ddd', borderRadius: 6, padding: 8, fontSize: 14, fontFamily: 'inherit' },
  sendBtn: { alignSelf: 'flex-end', padding: '8px 16px', background: '#20a7c9', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' },
};
