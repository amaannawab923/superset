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
 * Dev registration of the copilot as the active chat contribution. This runs at
 * app startup. The productionized form is a packaged .supx extension calling the
 * same `chat.registerChat`; this in-source registration keeps the local dev loop
 * fast (hot-reloads via the frontend dev server, no extension build/mount).
 */
import { chat } from 'src/core/chat';
import ChatTrigger from './ChatTrigger';
import ChatPanel from './ChatPanel';

chat.registerChat(
  { id: 'local.copilot', name: 'Copilot' },
  ChatTrigger,
  ChatPanel,
);
