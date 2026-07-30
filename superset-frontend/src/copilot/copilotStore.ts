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
 * Module-level chat state that OUTLIVES the panel component.
 *
 * The host mounts the panel in two different places (floating vs docked) with
 * different React keys, so switching display mode remounts the panel and would
 * reset any local `useState`. Keeping conversation id + messages here (outside
 * React) means the messages survive a mode switch. On a cold start the panel
 * rehydrates this store from the backend (the messages are persisted there).
 */
import { useSyncExternalStore } from 'react';

export interface Bubble {
  role: 'user' | 'assistant';
  content: string;
  streaming?: boolean;
  thoughts?: string[];
}

interface CopilotState {
  convId: string | null;
  messages: Bubble[];
  booted: boolean;
}

let state: CopilotState = { convId: null, messages: [], booted: false };
const listeners = new Set<() => void>();
const emit = () => listeners.forEach(l => l());

export const copilotStore = {
  getState: () => state,
  setConvId: (id: string | null) => {
    state = { ...state, convId: id };
    emit();
  },
  setMessages: (updater: (messages: Bubble[]) => Bubble[]) => {
    state = { ...state, messages: updater(state.messages) };
    emit();
  },
  replaceMessages: (messages: Bubble[]) => {
    state = { ...state, messages };
    emit();
  },
  markBooted: () => {
    state = { ...state, booted: true };
  },
  subscribe: (listener: () => void) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
};

export const useCopilotStore = () =>
  useSyncExternalStore(copilotStore.subscribe, copilotStore.getState);

/** Convert persisted A5 message rows into render bubbles (tool rows -> thoughts). */
export function rowsToBubbles(
  rows: Array<{
    role: string;
    content: string;
    tool_calls?: Array<{ name: string; arguments: unknown }> | null;
  }>,
): Bubble[] {
  const bubbles: Bubble[] = [];
  let thoughts: string[] = [];
  rows.forEach(m => {
    if (m.role === 'USER') {
      bubbles.push({ role: 'user', content: m.content });
    } else if (m.role === 'TOOL') {
      thoughts.push(`← ${String(m.content).slice(0, 120)}`);
    } else if (m.role === 'ASSISTANT') {
      (m.tool_calls || []).forEach(tc =>
        thoughts.push(`→ ${tc.name}(${JSON.stringify(tc.arguments)})`),
      );
      if (m.content) {
        bubbles.push({ role: 'assistant', content: m.content, thoughts });
        thoughts = [];
      }
    }
  });
  return bubbles;
}
