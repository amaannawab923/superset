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

// Shared types for the Copilot chat UI, plus the one piece still local-only:
// conversation groups. Conversations/messages themselves are now real, loaded
// from copilot-platform (see copilotClient.ts) — group membership, sort order,
// and fork lineage aren't backed by an API yet, so they stay client-side state
// layered on top of the real data (see Copilot.tsx).

export type ChatRole = 'user' | 'assistant';

export type ArtifactType = 'chart' | 'dashboard';

/** A chart or dashboard the agent created/touched during a turn, rendered as
 * a clickable card that opens the artifact preview panel. */
export interface Artifact {
  type: ArtifactType;
  id: number;
  name: string;
  url: string | null;
}

/** One step of Migration Buddy's "thinking" trace for a .twbx turn — see
 * MigrationProgressEvent in copilotClient.ts, the wire shape this mirrors. */
export interface MigrationStep {
  stage: 'parsing' | 'planning' | 'verifying' | 'applying' | 'assembling' | 'done' | 'error';
  tile: string | null;
  verdict: 'GREEN' | 'YELLOW' | 'RED' | null;
  detail: string;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  ts: number;
  artifacts?: Artifact[];
  migrationTrace?: MigrationStep[];
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
