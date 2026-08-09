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
import {
  ChangeEvent,
  KeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { styled } from '@apache-superset/core/theme';
import { t } from '@apache-superset/core/translation';
import { Dropdown, Icons } from '@superset-ui/core/components';
import { Conversation } from './dummyData';

const Panel = styled.div`
  flex: 1;
  height: 100%;
  display: flex;
  flex-direction: column;
  min-width: 0;
  ${({ theme }) => `background: ${theme.colorBgContainer};`}
`;

const PanelHeader = styled.div`
  ${({ theme }) => `
    padding: ${theme.sizeUnit * 3}px ${theme.sizeUnit * 4}px;
    border-bottom: 1px solid ${theme.colorBorderSecondary};
    font-weight: ${theme.fontWeightStrong};
    font-size: ${theme.fontSize}px;
  `}
`;

const Messages = styled.div`
  flex: 1;
  overflow-y: auto;
  ${({ theme }) => `padding: ${theme.sizeUnit * 6}px ${theme.sizeUnit * 4}px;`}
`;

const Center = styled.div`
  max-width: 760px;
  margin: 0 auto;
`;

const Row = styled.div<{ role: 'user' | 'assistant' }>`
  display: flex;
  justify-content: ${({ role }) => (role === 'user' ? 'flex-end' : 'flex-start')};
  ${({ theme }) => `margin-bottom: ${theme.sizeUnit * 4}px;`}
`;

const Bubble = styled.div<{ role: 'user' | 'assistant' }>`
  ${({ theme, role }) => `
    max-width: 78%;
    padding: ${theme.sizeUnit * 3}px ${theme.sizeUnit * 4}px;
    border-radius: ${theme.borderRadius * 2}px;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.5;
    font-size: ${theme.fontSize}px;
    background: ${role === 'user' ? theme.colorPrimary : theme.colorBgLayout};
    color: ${role === 'user' ? theme.colorTextLightSolid : theme.colorText};
    border: 1px solid ${role === 'user' ? theme.colorPrimary : theme.colorBorderSecondary};
  `}
`;

// --- Empty / welcome state (shown for a fresh conversation) ---

const EmptyState = styled.div`
  ${({ theme }) => `
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: ${theme.sizeUnit * 10}px ${theme.sizeUnit * 4}px;
  `}
`;

const EmptyInner = styled.div`
  width: 100%;
  max-width: 760px;
  margin: 0 auto;
`;

const Greeting = styled.h1`
  ${({ theme }) => `
    display: flex;
    align-items: center;
    justify-content: center;
    gap: ${theme.sizeUnit * 3}px;
    margin: 0 0 ${theme.sizeUnit * 8}px;
    font-size: ${theme.sizeUnit * 7}px;
    font-weight: ${theme.fontWeightStrong};
    color: ${theme.colorText};
    text-align: center;
  `}
`;

const GreetingIcon = styled.span`
  ${({ theme }) => `
    display: inline-flex;
    color: ${theme.colorPrimary};
  `}
`;

const IdeasLabel = styled.div`
  ${({ theme }) => `
    color: ${theme.colorTextSecondary};
    font-size: ${theme.fontSizeSM}px;
    margin: ${theme.sizeUnit * 8}px 0 ${theme.sizeUnit * 2}px;
    padding-left: ${theme.sizeUnit}px;
  `}
`;

const Idea = styled.button`
  ${({ theme }) => `
    display: flex;
    align-items: center;
    gap: ${theme.sizeUnit * 3}px;
    width: 100%;
    border: none;
    background: transparent;
    cursor: pointer;
    text-align: left;
    padding: ${theme.sizeUnit * 2}px ${theme.sizeUnit}px;
    border-radius: ${theme.borderRadius}px;
    color: ${theme.colorText};
    font-size: ${theme.fontSize}px;
    &:hover {
      background: ${theme.colorBgTextHover};
    }
  `}
`;

const IdeaIcon = styled.span`
  ${({ theme }) => `
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 auto;
    width: ${theme.sizeUnit * 8}px;
    height: ${theme.sizeUnit * 8}px;
    border-radius: ${theme.borderRadius}px;
    border: 1px solid ${theme.colorBorderSecondary};
    color: ${theme.colorTextSecondary};
  `}
`;

const Composer = styled.div`
  ${({ theme }) => `
    border-top: 1px solid ${theme.colorBorderSecondary};
    padding: ${theme.sizeUnit * 3}px ${theme.sizeUnit * 4}px;
  `}
`;

const ComposerInner = styled.div`
  max-width: 760px;
  margin: 0 auto;
`;

// The whole input is one rounded box (à la Claude Code): attachments on top,
// the textarea in the middle, and a controls row (attach + send) at the bottom.
const ComposerBox = styled.div`
  ${({ theme }) => `
    display: flex;
    flex-direction: column;
    gap: ${theme.sizeUnit * 2}px;
    padding: ${theme.sizeUnit * 2}px;
    border-radius: ${theme.borderRadius * 2}px;
    border: 1px solid ${theme.colorBorder};
    background: ${theme.colorBgContainer};
    &:focus-within {
      border-color: ${theme.colorPrimary};
    }
  `}
`;

const Attachments = styled.div`
  ${({ theme }) => `
    display: flex;
    flex-wrap: wrap;
    gap: ${theme.sizeUnit}px;
    padding: 0 ${theme.sizeUnit}px;
  `}
`;

const Chip = styled.span`
  ${({ theme }) => `
    display: inline-flex;
    align-items: center;
    gap: ${theme.sizeUnit}px;
    max-width: 240px;
    padding: ${theme.sizeUnit / 2}px ${theme.sizeUnit * 2}px;
    border-radius: ${theme.borderRadius}px;
    border: 1px solid ${theme.colorBorderSecondary};
    background: ${theme.colorBgLayout};
    color: ${theme.colorText};
    font-size: ${theme.fontSizeSM}px;
  `}
`;

const ChipName = styled.span`
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
`;

const ChipRemove = styled.button`
  ${({ theme }) => `
    display: inline-flex;
    align-items: center;
    border: none;
    background: transparent;
    cursor: pointer;
    padding: 0;
    color: ${theme.colorTextSecondary};
    &:hover {
      color: ${theme.colorText};
    }
  `}
`;

const TextArea = styled.textarea`
  ${({ theme }) => `
    resize: none;
    min-height: 40px;
    max-height: 200px;
    padding: ${theme.sizeUnit}px;
    border: none;
    background: transparent;
    color: ${theme.colorText};
    font-size: ${theme.fontSize}px;
    font-family: inherit;
    line-height: 1.5;
    &:focus {
      outline: none;
    }
  `}
`;

const Controls = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
`;

const IconButton = styled.button`
  ${({ theme }) => `
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: ${theme.sizeUnit * 8}px;
    height: ${theme.sizeUnit * 8}px;
    border-radius: 50%;
    border: 1px solid ${theme.colorBorder};
    background: transparent;
    color: ${theme.colorTextSecondary};
    cursor: pointer;
    &:hover {
      background: ${theme.colorBgTextHover};
      color: ${theme.colorText};
    }
  `}
`;

const SendButton = styled.button`
  ${({ theme }) => `
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: ${theme.sizeUnit * 8}px;
    height: ${theme.sizeUnit * 8}px;
    border-radius: 50%;
    border: none;
    cursor: pointer;
    background: ${theme.colorPrimary};
    color: ${theme.colorTextLightSolid};
    &:hover:not(:disabled) {
      opacity: 0.9;
    }
    &:disabled {
      cursor: not-allowed;
      background: ${theme.colorBgLayout};
      color: ${theme.colorTextTertiary};
      border: 1px solid ${theme.colorBorderSecondary};
    }
  `}
`;

export interface ChatPanelProps {
  conversation: Conversation;
  pending: boolean;
  onSend: (text: string) => void;
}

export default function ChatPanel({ conversation, pending, onSend }: ChatPanelProps) {
  const [text, setText] = useState('');
  const [attachments, setAttachments] = useState<string[]>([]);
  const endRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [conversation.messages.length, pending]);

  // A friendly greeting for the welcome screen: chosen from a pool that depends
  // on the user's local hour (so it reflects their timezone), picked once per
  // conversation so it stays stable across re-renders but varies for each new
  // chat.
  const greeting = useMemo(() => {
    const hour = new Date().getHours();
    let pool: string[];
    if (hour < 5 || hour >= 22) {
      pool = [
        t('Burning the midnight oil?'),
        t('Working late?'),
        t('Late-night jam session.'),
        t('The dashboards never sleep.'),
      ];
    } else if (hour < 12) {
      pool = [
        t('Good morning.'),
        t('Rise and shine.'),
        t('Morning — ready to migrate?'),
        t('Fresh start. What are we building?'),
      ];
    } else if (hour < 17) {
      pool = [
        t('Good afternoon.'),
        t('Welcome back.'),
        t('Afternoon — let’s migrate something.'),
        t('What are we porting today?'),
      ];
    } else {
      pool = [
        t('Good evening.'),
        t('Look who’s back.'),
        t('Evening — what’s on the board?'),
        t('Let’s wrap something up.'),
      ];
    }
    return pool[Math.floor(Math.random() * pool.length)];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversation.id]);

  const canSend = (!!text.trim() || attachments.length > 0) && !pending;

  const submit = () => {
    if (!canSend) return;
    const parts: string[] = [];
    if (attachments.length) parts.push(`📎 ${attachments.join(', ')}`);
    const trimmed = text.trim();
    if (trimmed) parts.push(trimmed);
    onSend(parts.join('\n'));
    setText('');
    setAttachments([]);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const openFilePicker = () => fileInputRef.current?.click();

  const onFilesChosen = (e: ChangeEvent<HTMLInputElement>) => {
    const names = Array.from(e.target.files ?? []).map(f => f.name);
    if (names.length) setAttachments(prev => [...prev, ...names]);
    // Reset so picking the same file again still fires onChange.
    e.target.value = '';
  };

  const removeAttachment = (name: string) =>
    setAttachments(prev => prev.filter(n => n !== name));

  // The composer is identical in both the welcome and the chat layouts, so it
  // is built once here and placed in whichever container is active.
  const composer = (
    <ComposerBox>
      {attachments.length > 0 && (
        <Attachments data-test="copilot-attachments">
          {attachments.map(name => (
            <Chip key={name}>
              <Icons.FileOutlined iconSize="s" />
              <ChipName>{name}</ChipName>
              <ChipRemove
                onClick={() => removeAttachment(name)}
                aria-label={t('Remove attachment')}
              >
                <Icons.CloseOutlined iconSize="s" />
              </ChipRemove>
            </Chip>
          ))}
        </Attachments>
      )}
      <TextArea
        value={text}
        placeholder={t('Ask the Copilot to migrate a dashboard, or anything…')}
        onChange={e => setText(e.target.value)}
        onKeyDown={onKeyDown}
        data-test="copilot-input"
      />
      <Controls>
        <Dropdown
          trigger={['click']}
          menu={{
            items: [
              {
                key: 'add',
                icon: <Icons.FileOutlined />,
                label: t('Add'),
              },
            ],
            onClick: ({ key }) => {
              if (key === 'add') openFilePicker();
            },
          }}
        >
          <IconButton
            aria-label={t('Add attachment')}
            data-test="copilot-attach"
          >
            <Icons.PlusOutlined iconSize="s" />
          </IconButton>
        </Dropdown>
        <SendButton
          disabled={!canSend}
          onClick={submit}
          aria-label={t('Send')}
          data-test="copilot-send"
        >
          <Icons.UpOutlined iconSize="s" />
        </SendButton>
      </Controls>
      <input
        ref={fileInputRef}
        type="file"
        accept=".twbx"
        multiple
        hidden
        onChange={onFilesChosen}
        data-test="copilot-file-input"
      />
    </ComposerBox>
  );

  // Fresh conversation → a centered, Claude-style welcome screen. As soon as a
  // message exists, we fall through to the normal chat transcript below.
  if (conversation.messages.length === 0) {
    const suggestions = [
      {
        icon: <Icons.UploadOutlined />,
        label: t('Migrate a Tableau dashboard to Superset'),
      },
      {
        icon: <Icons.FileOutlined />,
        label: t('Explain a fidelity report'),
      },
      {
        icon: <Icons.CheckCircleOutlined />,
        label: t("Verify a tile's numbers against the extract"),
      },
    ];

    return (
      <Panel data-test="copilot-chat-panel">
        <EmptyState data-test="copilot-empty-state">
          <EmptyInner>
            <Greeting>
              <GreetingIcon>
                <Icons.ThunderboltOutlined />
              </GreetingIcon>
              {greeting}
            </Greeting>
            {composer}
            <IdeasLabel>{t('Ideas for you')}</IdeasLabel>
            {suggestions.map(s => (
              <Idea
                key={s.label}
                onClick={() => onSend(s.label)}
                data-test="copilot-idea"
              >
                <IdeaIcon>{s.icon}</IdeaIcon>
                {s.label}
              </Idea>
            ))}
          </EmptyInner>
        </EmptyState>
      </Panel>
    );
  }

  return (
    <Panel data-test="copilot-chat-panel">
      <PanelHeader>{conversation.title}</PanelHeader>
      <Messages>
        <Center>
          {conversation.messages.map(m => (
            <Row key={m.id} role={m.role}>
              <Bubble role={m.role}>{m.content}</Bubble>
            </Row>
          ))}
          {pending && (
            <Row role="assistant">
              <Bubble role="assistant">{t('Thinking…')}</Bubble>
            </Row>
          )}
          <div ref={endRef} />
        </Center>
      </Messages>
      <Composer>
        <ComposerInner>{composer}</ComposerInner>
      </Composer>
    </Panel>
  );
}
