import { CustomCellRendererProps } from 'ag-grid-react';
import {
  css,
  isProbablyHTML,
  JsonObject,
  sanitizeHtml,
  styled,
} from '@superset-ui/core';
import { isActiveFilterValue } from '../../../common/utils/isActiveFilterValue';

const NoWrapSpan = styled.span`
  white-space: nowrap;
`;

export const GroupCellRenderer = (
  props: CustomCellRendererProps & {
    allowRenderHtml?: boolean;
    sliceId: number;
    selectedFilters?: JsonObject;
  },
) => {
  const isRootLevel = props.node.level === -1;
  if (isRootLevel) {
    return <span>Total</span>;
  }

  const activeClassName =
    props.node.field &&
    isActiveFilterValue(props.selectedFilters, props.node.field, props.value)
      ? 'active-filter-cell'
      : '';

  if (typeof props.value === 'string') {
    if (
      props.value.startsWith('http://') ||
      props.value.startsWith('https://')
    ) {
      return (
        <a
          href={props.value}
          target="_blank"
          rel="noopener noreferrer"
          className={activeClassName}
          css={css`
            display: flex;
            align-items: center;
          `}
        >
          {props.value} <NoWrapSpan>({props.node.allChildrenCount})</NoWrapSpan>
        </a>
      );
    }
    if (props.allowRenderHtml && isProbablyHTML(props.value)) {
      return (
        <div
          dangerouslySetInnerHTML={{ __html: sanitizeHtml(props.value) }}
          className={activeClassName}
        />
      );
    }
  }
  return (
    <span className={activeClassName}>
      {props.valueFormatted ?? props.value}{' '}
      <NoWrapSpan>({props.node.allChildrenCount})</NoWrapSpan>
    </span>
  );
};
