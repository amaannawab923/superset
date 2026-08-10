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

/**
 * Client for the standalone copilot-platform backend (FastAPI, :8000 by
 * default — override with `window.__COPILOT_BASE_URL__`). Ported from the
 * copilot branch's tested src/copilot/copilotClient.ts, trimmed to what this
 * page's conversation list + chat panel need.
 */

const BASE_URL: string =
  (window as unknown as { __COPILOT_BASE_URL__?: string }).__COPILOT_BASE_URL__ ||
  'http://localhost:8000';

const API = `${BASE_URL}/api/v1/copilot`;

export type BackendMessageRole = 'USER' | 'ASSISTANT' | 'SYSTEM' | 'TOOL';
export type BackendConversationStatus = 'ACTIVE' | 'ARCHIVED' | 'DELETED';

export interface BackendArtifact {
  type: 'chart';
  id: number;
  name: string;
  url: string | null;
}

export interface ConversationOut {
  id: string;
  title: string | null;
  title_source: 'SYSTEM' | 'USER';
  agent_type: string;
  status: BackendConversationStatus;
  last_message_at: string | null;
  created_at: string;
  message_count: number;
  metadata_json: Record<string, unknown>;
}

export interface MessageRow {
  id: string;
  conversation_id: string;
  role: BackendMessageRole;
  content: string;
  tool_calls?: Array<{ name: string; arguments: unknown }> | null;
  artifacts?: BackendArtifact[] | null;
  created_at: string;
  metadata_json?: Record<string, unknown> | null;
}

async function asJson<T>(res: Response, action: string): Promise<T> {
  if (!res.ok) {
    throw new Error(`${action} failed: ${res.status}`);
  }
  return res.json();
}

export async function createConversation(
  agentType = 'DEFAULT',
  title?: string,
): Promise<ConversationOut> {
  const res = await fetch(`${API}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_type: agentType, title }),
  });
  return asJson(res, 'createConversation');
}

export async function listConversations(): Promise<ConversationOut[]> {
  const res = await fetch(`${API}/conversations?limit=200`);
  return asJson(res, 'listConversations');
}

export async function listMessages(
  conversationId: string,
): Promise<MessageRow[]> {
  const res = await fetch(`${API}/conversations/${conversationId}/messages`);
  return asJson(res, 'listMessages');
}

export async function patchConversation(
  conversationId: string,
  patch: { title?: string; status?: BackendConversationStatus; pinned?: boolean },
): Promise<ConversationOut> {
  const res = await fetch(`${API}/conversations/${conversationId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  return asJson(res, 'patchConversation');
}

export async function deleteConversation(conversationId: string): Promise<void> {
  const res = await fetch(`${API}/conversations/${conversationId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(`deleteConversation failed: ${res.status}`);
}

export interface StreamHandlers {
  onToken?: (text: string) => void;
  onToolCall?: (name: string, args: unknown) => void;
  onToolResult?: (content: string) => void;
  onArtifacts?: (artifacts: BackendArtifact[]) => void;
  onFinal?: (content: string) => void;
  onDone?: (status: string) => void;
  onError?: (message: string) => void;
}

/** Parse and dispatch one backend SSE stream (token/tool_call/tool_result/
 * artifacts/final/token_status/error), same wire format as the copilot
 * branch's client, plus the artifacts event this page adds. */
export async function streamCompletion(
  conversationId: string,
  message: string,
  handlers: StreamHandlers,
): Promise<void> {
  const res = await fetch(`${API}/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_id: conversationId, message }),
  });
  if (!res.ok || !res.body) {
    handlers.onError?.(`completions failed: ${res.status}`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const dispatch = (event: string, data: Record<string, unknown>) => {
    switch (event) {
      case 'token':
        handlers.onToken?.(String(data.text ?? ''));
        break;
      case 'tool_call':
        handlers.onToolCall?.(String(data.name ?? ''), data.arguments);
        break;
      case 'tool_result':
        handlers.onToolResult?.(String(data.content ?? ''));
        break;
      case 'artifacts':
        handlers.onArtifacts?.((data.artifacts as BackendArtifact[]) ?? []);
        break;
      case 'final':
        handlers.onFinal?.(String(data.content ?? ''));
        break;
      case 'token_status':
        handlers.onDone?.(String(data.status ?? 'done'));
        break;
      case 'error':
        handlers.onError?.(String(data.message ?? 'error'));
        break;
      default:
        break;
    }
  };

  const parseRecord = (record: string) => {
    let event = 'message';
    const dataLines: string[] = [];
    record.split('\n').forEach(line => {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
    });
    if (!dataLines.length) return;
    try {
      dispatch(event, JSON.parse(dataLines.join('\n')));
    } catch {
      // ignore malformed record
    }
  };

  for (;;) {
    // eslint-disable-next-line no-await-in-loop
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx = buffer.indexOf('\n\n');
    while (idx !== -1) {
      const record = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (record.trim()) parseRecord(record);
      idx = buffer.indexOf('\n\n');
    }
  }
  if (buffer.trim()) parseRecord(buffer);
}
