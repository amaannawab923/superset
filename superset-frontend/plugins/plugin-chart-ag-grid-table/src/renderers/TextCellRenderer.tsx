import { CustomCellRendererProps } from 'ag-grid-react';
import {
  css,
  isProbablyHTML,
  sanitizeHtml,
  t,
  styled,
} from '@superset-ui/core';
import { InfoCircleOutlined } from '@ant-design/icons';
import { Tooltip } from '@superset-ui/chart-controls';
import { InputColumn } from '../AgGridTable/transformData';

const SummaryContainer = styled.div`
  ${({ theme }) => `
    display: flex;
    align-items: center;
    gap: ${theme.gridUnit}px;
  `}
`;

const SummaryText = styled.div`
  ${({ theme }) => `
    font-weight: ${theme.typography.weights.bold};
  `}
`;

const SUMMARY_TOOLTIP_TEXT = t(
  'Show total aggregations of selected metrics. Note that row limit does not apply to the result.',
);

export const TextCellRenderer = (
  params: CustomCellRendererProps & {
    allowRenderHtml?: boolean;
    sliceId: number;
    columns: InputColumn[];
  },
) => {
  const { node, api, colDef, columns, allowRenderHtml, value, valueFormatted } =
    params;

  if (node?.rowPinned === 'bottom') {
    const cols = api.getAllGridColumns().filter(col => col.isVisible());
    const colAggCheck = !cols[0].getAggFunc();
    if (cols.length > 1 && colAggCheck && columns[0].key === colDef?.field) {
      return (
        <SummaryContainer>
          <SummaryText>{t('Summary')}</SummaryText>
          <Tooltip overlay={SUMMARY_TOOLTIP_TEXT}>
            <InfoCircleOutlined />
          </Tooltip>
        </SummaryContainer>
      );
    }
    if (!value) {
      return null;
    }
  }

  if (!(typeof value === 'string' || value instanceof Date)) {
    return valueFormatted ?? value;
  }

  if (typeof value === 'string') {
    if (value.startsWith('http://') || value.startsWith('https://')) {
      return (
        <a
          href={value}
          target="_blank"
          rel="noopener noreferrer"
          css={css`
            display: flex;
            align-items: center;
          `}
        >
          {value}
        </a>
      );
    }
    if (allowRenderHtml && isProbablyHTML(value)) {
      return <div dangerouslySetInnerHTML={{ __html: sanitizeHtml(value) }} />;
    }
  }

  return (
    <div
      css={css`
        display: flex;
        align-items: center;
      `}
    >
      {valueFormatted ?? value}
    </div>
  );
};
