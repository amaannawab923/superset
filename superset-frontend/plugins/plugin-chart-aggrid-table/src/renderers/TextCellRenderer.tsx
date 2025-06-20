import { CustomCellRendererProps } from 'ag-grid-react';
import { useSelector } from 'react-redux';
import {
  css,
  isProbablyHTML,
  sanitizeHtml,
  t,
  SupersetTheme,
} from '@superset-ui/core';
import { RootState } from 'src/dashboard/types';
import { isActiveFilterValue } from '../common/utils/isActiveFilterValue';

export const TextCellRenderer = (
  params: CustomCellRendererProps & {
    allowRenderHtml?: boolean;
    sliceId: number;
  },
) => {
  const filters = useSelector(
    (state: RootState) =>
      state.dataMask?.[params.sliceId]?.filterState?.filters,
  );

  if (params.node.footer) {
    const cols = params.api.getAllGridColumns().filter(col => col.isVisible());
    if (
      cols.length > 1 &&
      !cols[0].getAggFunc() &&
      cols[0].getColId() === params.column?.getColId()
    ) {
      return (
        <span
          css={(theme: SupersetTheme) => css`
            color: var(--ag-cell-text-color);
            font-weight: ${theme.typography.weights.medium};
          `}
        >
          {t('Summary')}
        </span>
      );
    }
  }

  if (!(typeof params.value === 'string' || params.value instanceof Date)) {
    return params.valueFormatted ?? params.value;
  }

  const activeClassName =
    params.column &&
    isActiveFilterValue(filters, params.column.getColId(), params.value)
      ? 'active-filter-cell'
      : '';

  if (typeof params.value === 'string') {
    if (
      params.value.startsWith('http://') ||
      params.value.startsWith('https://')
    ) {
      return (
        <a
          href={params.value}
          target="_blank"
          rel="noopener noreferrer"
          className={activeClassName}
          css={css`
            display: flex;
            align-items: center;
          `}
        >
          {params.value}
        </a>
      );
    }
    if (params.allowRenderHtml && isProbablyHTML(params.value)) {
      return (
        <div
          dangerouslySetInnerHTML={{ __html: sanitizeHtml(params.value) }}
          className={activeClassName}
        />
      );
    }
  }
  return (
    <div
      className={activeClassName}
      css={css`
        display: flex;
        align-items: center;
      `}
    >
      {params.valueFormatted ?? params.value}
    </div>
  );
};
