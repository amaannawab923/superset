/**
 * Extension entry point — the single `./index` module Superset loads.
 * Registers our copilot as the active chat provider (host owns layout /
 * open-close / display mode; we provide the Trigger + Panel).
 */
import { chat } from '@apache-superset/core';
import ChatTrigger from './ChatTrigger';
import ChatPanel from './ChatPanel';

chat.registerChat(
  { id: 'local.copilot', name: 'Copilot', description: 'BI copilot (Part A backend)' },
  ChatTrigger,
  ChatPanel,
);
