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
import { styled } from '@apache-superset/core/theme';
import { t } from '@apache-superset/core/translation';
import { Icons } from '@superset-ui/core/components';
import { Artifact } from './dummyData';

const Panel = styled.div`
  ${({ theme }) => `
    width: 480px;
    min-width: 480px;
    height: 100%;
    display: flex;
    flex-direction: column;
    border-left: 1px solid ${theme.colorBorderSecondary};
    background: ${theme.colorBgContainer};
  `}
`;

const Header = styled.div`
  ${({ theme }) => `
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: ${theme.sizeUnit * 2}px;
    padding: ${theme.sizeUnit * 3}px ${theme.sizeUnit * 4}px;
    border-bottom: 1px solid ${theme.colorBorderSecondary};
  `}
`;

const Title = styled.div`
  ${({ theme }) => `
    display: flex;
    align-items: center;
    gap: ${theme.sizeUnit * 2}px;
    font-weight: ${theme.fontWeightStrong};
    font-size: ${theme.fontSize}px;
    color: ${theme.colorText};
  `}
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const CloseButton = styled.button`
  ${({ theme }) => `
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: center;
    width: ${theme.sizeUnit * 8}px;
    height: ${theme.sizeUnit * 8}px;
    border: none;
    background: transparent;
    border-radius: ${theme.borderRadius}px;
    cursor: pointer;
    color: ${theme.colorTextSecondary};
    &:hover {
      background: ${theme.colorBgTextHover};
      color: ${theme.colorText};
    }
  `}
`;

const Frame = styled.iframe`
  flex: 1;
  width: 100%;
  border: none;
`;

const EmptyPreview = styled.div`
  ${({ theme }) => `
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: ${theme.sizeUnit * 4}px;
    color: ${theme.colorTextSecondary};
    text-align: center;
  `}
`;

// The backend may report an origin the frontend can't reach (e.g. a dev-only
// config pointing at a different port than this page is served from) — take
// only the path + query it gave us and resolve it against this page's own
// origin, which is always correct for wherever the app actually runs.
function toSameOriginUrl(url: string): string | null {
  try {
    const parsed = new URL(url, window.location.origin);
    const separator = parsed.search ? '&' : '?';
    return `${window.location.origin}${parsed.pathname}${parsed.search}${separator}standalone=1`;
  } catch {
    return null;
  }
}

export interface ChartPreviewPanelProps {
  artifact: Artifact | null;
  onClose: () => void;
}

export default function ChartPreviewPanel({ artifact, onClose }: ChartPreviewPanelProps) {
  if (!artifact) return null;

  const src = artifact.url ? toSameOriginUrl(artifact.url) : null;

  return (
    <Panel data-test="copilot-chart-preview-panel">
      <Header>
        <Title>
          <Icons.BarChartOutlined iconSize="s" />
          <span>{artifact.name}</span>
        </Title>
        <CloseButton onClick={onClose} aria-label={t('Close preview')}>
          <Icons.CloseOutlined iconSize="s" />
        </CloseButton>
      </Header>
      {src ? (
        <Frame src={src} title={artifact.name} data-test="copilot-chart-preview-frame" />
      ) : (
        <EmptyPreview>{t('No preview URL available for this chart.')}</EmptyPreview>
      )}
    </Panel>
  );
}
