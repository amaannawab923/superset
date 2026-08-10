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
import { useCallback, useEffect, useRef, useState } from 'react';
import { styled } from '@apache-superset/core/theme';
import { t } from '@apache-superset/core/translation';
import { Icons } from '@superset-ui/core/components';
import { Artifact } from './dummyData';

const MIN_WIDTH = 360;
const MAX_WIDTH = 900;
const DEFAULT_WIDTH = 480;

const Panel = styled.div`
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
  flex: 0 0 auto;
  ${({ theme }) => `
    border-left: 1px solid ${theme.colorBorderSecondary};
    background: ${theme.colorBgContainer};
  `}
`;

const ResizeHandle = styled.div`
  position: absolute;
  top: 0;
  bottom: 0;
  left: -5px;
  width: 10px;
  cursor: col-resize;
  z-index: 1;
  display: flex;
  justify-content: center;
  background: transparent;
  &:hover > span,
  &:active > span {
    ${({ theme }) => `background: ${theme.colorPrimary};`}
  }
`;

// A slim visible line centered inside the wider (easier-to-grab) hit area.
const ResizeHandleBar = styled.span`
  width: 2px;
  height: 100%;
  background: transparent;
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

const ARTIFACT_ICON = {
  chart: Icons.BarChartOutlined,
  dashboard: Icons.DashboardOutlined,
};

export interface ArtifactPreviewPanelProps {
  artifact: Artifact | null;
  onClose: () => void;
}

export default function ArtifactPreviewPanel({
  artifact,
  onClose,
}: ArtifactPreviewPanelProps) {
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef<{ x: number; width: number } | null>(null);

  const onHandlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault();
      dragStart.current = { x: e.clientX, width };
      setDragging(true);
    },
    [width],
  );

  // The panel sits on the right edge of the screen, so dragging the handle
  // left (cursor moves left of where the drag started) should grow it.
  useEffect(() => {
    if (!dragging) return undefined;
    const onMove = (e: PointerEvent) => {
      if (!dragStart.current) return;
      const delta = dragStart.current.x - e.clientX;
      setWidth(
        Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, dragStart.current.width + delta)),
      );
    };
    const onUp = () => {
      dragStart.current = null;
      setDragging(false);
    };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [dragging]);

  if (!artifact) return null;

  const src = artifact.url ? toSameOriginUrl(artifact.url) : null;
  const ArtifactIcon = ARTIFACT_ICON[artifact.type];

  return (
    <Panel
      data-test="copilot-artifact-preview-panel"
      style={{ width, minWidth: MIN_WIDTH, maxWidth: MAX_WIDTH }}
    >
      <ResizeHandle
        onPointerDown={onHandlePointerDown}
        data-test="copilot-artifact-preview-resize-handle"
        role="separator"
        aria-orientation="vertical"
        aria-label={t('Resize preview panel')}
      >
        <ResizeHandleBar />
      </ResizeHandle>
      <Header>
        <Title>
          <ArtifactIcon iconSize="s" />
          <span>{artifact.name}</span>
        </Title>
        <CloseButton onClick={onClose} aria-label={t('Close preview')}>
          <Icons.CloseOutlined iconSize="s" />
        </CloseButton>
      </Header>
      {src ? (
        <Frame
          src={src}
          title={artifact.name}
          data-test="copilot-artifact-preview-frame"
          // Iframes swallow pointer events, which would otherwise break the
          // drag the moment the cursor crosses over it mid-resize.
          style={dragging ? { pointerEvents: 'none' } : undefined}
        />
      ) : (
        <EmptyPreview>{t('No preview URL available for this %s.', artifact.type)}</EmptyPreview>
      )}
    </Panel>
  );
}
