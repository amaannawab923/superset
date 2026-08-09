import React, { useEffect, useState } from 'react';
import { chat } from '@apache-superset/core';

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
