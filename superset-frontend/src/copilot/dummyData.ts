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

// Local, in-memory data model for the Copilot chat UI. This is a stub layer:
// the shapes mirror what the real agent backend will return, but the responses
// are canned so we can build the UI ahead of wiring the LangGraph agent.

export type ChatRole = 'user' | 'assistant';

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  ts: number;
}

export interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
  updatedAt: number;
  /** Pinned chats float to a dedicated section at the top of the list. */
  pinned?: boolean;
  /** Archived chats are hidden from the main list. */
  archived?: boolean;
  /** Membership in a user-defined group/category (null = ungrouped). */
  groupId?: string | null;
}

/** A user-defined category that conversations can be organised into. */
export interface ConversationGroup {
  id: string;
  name: string;
}

export const seedGroups: ConversationGroup[] = [
  { id: 'g_migrations', name: 'Tableau migrations' },
];

let seq = 0;
export const uid = (prefix = 'id'): string => {
  seq += 1;
  return `${prefix}_${seq}_${Math.floor(performance.now())}`;
};

const now = Date.now();
const min = 60_000;

export const seedConversations: Conversation[] = [
  // --- Pinned ---
  {
    id: 'c_migrate_superstore',
    title: 'Migrate Superstore dashboard',
    updatedAt: now - 2 * min,
    pinned: true,
    messages: [
      {
        id: 'm1',
        role: 'user',
        content: 'Migrate the Superstore Overview dashboard from Tableau to Superset.',
        ts: now - 6 * min,
      },
      {
        id: 'm2',
        role: 'assistant',
        content:
          'Parsed the workbook: 9 measure tiles, 6 datasources, 111 calculated fields. ' +
          '7 tiles verified against the extract (numbers match to 10 decimals), 2 flagged ' +
          'yellow (LOD expressions need a rendered oracle). No tile shipped unverified.',
        ts: now - 5 * min,
      },
    ],
  },
  // --- Group: Tableau migrations ---
  {
    id: 'c_q3_parity',
    title: 'Q3 revenue dashboard parity',
    updatedAt: now - 20 * min,
    groupId: 'g_migrations',
    messages: [
      {
        id: 'm1',
        role: 'user',
        content: 'Check the Q3 revenue workbook migrates with matching totals.',
        ts: now - 22 * min,
      },
      {
        id: 'm2',
        role: 'assistant',
        content:
          '5 of 5 tiles GREEN — every measure matches the extract to 10 decimals. '
          + 'Ready to publish.',
        ts: now - 20 * min,
      },
    ],
  },
  {
    id: 'c_lod',
    title: 'LOD expression translation',
    updatedAt: now - 90 * min,
    groupId: 'g_migrations',
    messages: [
      {
        id: 'm1',
        role: 'user',
        content: 'How do you translate a FIXED LOD to Superset SQL?',
        ts: now - 92 * min,
      },
      {
        id: 'm2',
        role: 'assistant',
        content:
          'A FIXED LOD becomes a windowed aggregate (or a subquery join) keyed on the '
          + 'FIXED dimensions. If the numbers cannot be verified against the extract, the '
          + 'tile is flagged YELLOW rather than shipped.',
        ts: now - 90 * min,
      },
    ],
  },
  // --- Chats (ungrouped) ---
  {
    id: 'c_fidelity',
    title: 'Explain a fidelity report',
    updatedAt: now - 40 * min,
    messages: [
      {
        id: 'm1',
        role: 'user',
        content: 'What does a yellow verdict mean in the fidelity report?',
        ts: now - 41 * min,
      },
      {
        id: 'm2',
        role: 'assistant',
        content:
          'Yellow means the tile renders and structurally matches the source, but the ' +
          'data-oracle could not verify its numbers (usually an LOD or table-calc). It ' +
          'is flagged for a rendered oracle or a human — never shipped as green.',
        ts: now - 40 * min,
      },
    ],
  },
  {
    id: 'c_new',
    title: 'New conversation',
    updatedAt: now - 3 * 60 * min,
    messages: [],
  },
];

const CANNED = [
  'Here is a stubbed response. The Copilot backend is not wired yet, so I am echoing '
    + 'a placeholder so we can build and iterate on the interface.',
  'Got it. Once the LangGraph migration agent is connected, this is where the real, '
    + 'tool-grounded answer (with the fidelity report) will stream in.',
  'Understood. I would parse the workbook, translate each tile to SQL, verify the '
    + 'numbers against the extract, and flag anything I could not verify.',
];

/** Deterministic-ish canned reply so the UI feels alive before the agent exists. */
export function dummyReply(userText: string): string {
  const t = userText.toLowerCase();
  if (t.includes('migrate') || t.includes('tableau')) {
    return (
      'I would run the migration pipeline on that workbook: parse the .twb, resolve '
      + 'calcs/LODs to SQL, build the Superset charts, and verify each tile against the '
      + '.hyper extract. You would get a fidelity report of green / yellow / red tiles. '
      + '(Stubbed for now — agent not yet connected.)'
    );
  }
  if (t.includes('fidelity') || t.includes('verify')) {
    return (
      'Every tile carries a verdict: GREEN (numbers + structure match), YELLOW (renders '
      + 'but unverified — needs a rendered oracle or a human), RED (no equivalent or a '
      + 'failed check). Nothing unverified is ever shipped green. (Stubbed response.)'
    );
  }
  return CANNED[Math.abs(hash(userText)) % CANNED.length];
}

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i += 1) {
    h = (h << 5) - h + s.charCodeAt(i);
    h |= 0;
  }
  return h;
}
