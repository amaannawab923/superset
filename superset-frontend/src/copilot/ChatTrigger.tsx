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
import { useEffect, useState } from 'react';
import { chat } from 'src/core/chat';

export default function ChatTrigger() {
  const [open, setOpen] = useState(chat.isOpen());

  useEffect(() => {
    const o = chat.onDidOpen(() => setOpen(true));
    const c = chat.onDidClose(() => setOpen(false));
    return () => {
      o.dispose();
      c.dispose();
    };
  }, []);

  return (
    <button
      type="button"
      title="Copilot"
      onClick={() => (open ? chat.close() : chat.open())}
      style={{
        width: 48,
        height: 48,
        borderRadius: 24,
        border: 'none',
        background: '#20a7c9',
        color: '#fff',
        fontSize: 22,
        cursor: 'pointer',
        boxShadow: '0 2px 8px rgba(0,0,0,0.25)',
      }}
    >
      {open ? '×' : '💬'}
    </button>
  );
}
