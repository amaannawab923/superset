/**
 * Client for the standalone copilot backend (the Part A FastAPI service).
 * Handles conversation creation and SSE streaming of a completion.
 *
 * Base URL is overridable via `window.__COPILOT_BASE_URL__` so the same build
 * works against a sidecar in dev and a same-origin backend later.
 */

const BASE_URL: string =
  (typeof window !== 'undefined' && (window as any).__COPILOT_BASE_URL__) ||
  'http://localhost:8000';

const API = `${BASE_URL}/api/v1/copilot`;

export interface StreamHandlers {
  onRunStarted?: (runId: string) => void;
  onToken?: (text: string) => void;
  onToolCall?: (name: string, args: unknown) => void;
  onToolResult?: (content: string) => void;
  onFinal?: (content: string) => void;
  onUsage?: (promptTokens: number, completionTokens: number) => void;
  onDone?: (status: string) => void;
  onError?: (message: string) => void;
}

export async function createConversation(
  agentType = 'DEFAULT',
): Promise<{ id: string; title: string | null }> {
  const res = await fetch(`${API}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_type: agentType }),
  });
  if (!res.ok) throw new Error(`createConversation failed: ${res.status}`);
  return res.json();
}

/**
 * POST /completions and parse the SSE stream. EventSource can't POST, so we
 * read the ReadableStream and split on the SSE record boundary ("\n\n").
 */
export async function streamCompletion(
  conversationId: string,
  message: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API}/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_id: conversationId, message }),
    signal,
  });
  if (!res.ok || !res.body) {
    handlers.onError?.(`completions failed: ${res.status}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const dispatch = (event: string, data: any) => {
    switch (event) {
      case 'run_started':
        handlers.onRunStarted?.(data.run_id);
        break;
      case 'token':
        handlers.onToken?.(data.text);
        break;
      case 'tool_call':
        handlers.onToolCall?.(data.name, data.arguments);
        break;
      case 'tool_result':
        handlers.onToolResult?.(data.content);
        break;
      case 'final':
        handlers.onFinal?.(data.content);
        break;
      case 'usage':
        handlers.onUsage?.(data.prompt_tokens, data.completion_tokens);
        break;
      case 'token_status':
        handlers.onDone?.(data.status);
        break;
      case 'error':
        handlers.onError?.(data.message);
        break;
      default:
        break;
    }
  };

  const parseRecord = (record: string) => {
    let event = 'message';
    const dataLines: string[] = [];
    for (const line of record.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
    }
    if (!dataLines.length) return;
    try {
      dispatch(event, JSON.parse(dataLines.join('\n')));
    } catch {
      /* ignore malformed record */
    }
  };

  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    // eslint-disable-next-line no-cond-assign
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const record = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (record.trim()) parseRecord(record);
    }
  }
  if (buffer.trim()) parseRecord(buffer);
}
