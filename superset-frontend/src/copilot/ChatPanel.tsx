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
import { KeyboardEvent, useEffect, useRef, useState } from 'react';
import { styled } from '@apache-superset/core/theme';
import { t } from '@apache-superset/core/translation';
import { Button } from '@superset-ui/core/components';
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

const Empty = styled.div`
  ${({ theme }) => `
    color: ${theme.colorTextSecondary};
    text-align: center;
    margin-top: ${theme.sizeUnit * 20}px;
    font-size: ${theme.fontSizeLG}px;
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
  display: flex;
  ${({ theme }) => `gap: ${theme.sizeUnit * 2}px;`}
  align-items: flex-end;
`;

const TextArea = styled.textarea`
  ${({ theme }) => `
    flex: 1;
    resize: none;
    min-height: 44px;
    max-height: 200px;
    padding: ${theme.sizeUnit * 2}px ${theme.sizeUnit * 3}px;
    border-radius: ${theme.borderRadius}px;
    border: 1px solid ${theme.colorBorder};
    background: ${theme.colorBgContainer};
    color: ${theme.colorText};
    font-size: ${theme.fontSize}px;
    font-family: inherit;
    line-height: 1.5;
    &:focus {
      outline: none;
      border-color: ${theme.colorPrimary};
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
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [conversation.messages.length, pending]);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || pending) return;
    onSend(trimmed);
    setText('');
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <Panel data-test="copilot-chat-panel">
      <PanelHeader>{conversation.title}</PanelHeader>
      <Messages>
        <Center>
          {conversation.messages.length === 0 && (
            <Empty>{t('Start the conversation below.')}</Empty>
          )}
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
        <ComposerInner>
          <TextArea
            value={text}
            placeholder={t('Ask the Copilot to migrate a dashboard, or anything…')}
            onChange={e => setText(e.target.value)}
            onKeyDown={onKeyDown}
            data-test="copilot-input"
          />
          <Button
            buttonStyle="primary"
            disabled={!text.trim() || pending}
            onClick={submit}
            data-test="copilot-send"
          >
            {t('Send')}
          </Button>
        </ComposerInner>
      </Composer>
    </Panel>
  );
}
