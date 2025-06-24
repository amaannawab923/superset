import { CustomCellRendererProps } from 'ag-grid-react';
import { css, useTheme } from '@superset-ui/core';
import { useSelector } from 'react-redux';
import { RootState } from 'src/dashboard/types';
import {
  ColorSchemeEnum,
  isSimpleValue,
  TableChartTransformedProps,
  ValueRange,
} from '../types';
import { COMPARISON_LABELS } from '../consts';
// @ts-ignore
import { isActiveFilterValue } from '../../common/utils/isActiveFilterValue';

const getCellWidth = (
  value: number,
  valueRange: ValueRange,
  alignPositiveNegative?: boolean,
) => {
  const [minValue, maxValue] = valueRange;
  if (alignPositiveNegative) {
    const perc = Math.abs(Math.round((value / maxValue) * 100));
    return perc;
  }
  const posExtent = Math.abs(Math.max(maxValue, 0));
  const negExtent = Math.abs(Math.min(minValue, 0));
  const tot = posExtent + negExtent;
  const perc2 = Math.round((Math.abs(value) / tot) * 100);
  return perc2;
};

const getCellOffset = (
  value: number,
  valueRange: ValueRange,
  alignPositiveNegative?: boolean,
) => {
  if (alignPositiveNegative) {
    return 0;
  }
  const [minValue, maxValue] = valueRange;
  const posExtent = Math.abs(Math.max(maxValue, 0));
  const negExtent = Math.abs(Math.min(minValue, 0));
  const tot = posExtent + negExtent;
  return Math.round((Math.min(negExtent + value, negExtent) / tot) * 100);
};

const getCellBackground = (value: number, colorPositiveNegative?: boolean) => {
  const r = colorPositiveNegative && value < 0 ? 150 : 0;
  return `rgba(${r},0,0,0.2)`;
};

const getValueFromParams = (params: CustomCellRendererProps) => {
  // for some reason in raw records mode, value and formattedValue are sometimes objects
  const value = isSimpleValue(params.value)
    ? params.value
    : params.value?.value;
  const valueFormatted = isSimpleValue(params.valueFormatted)
    ? params.valueFormatted
    : (params.valueFormatted as { value: number | string })?.value;

  return { value, valueFormatted };
};
export const NumericCellRenderer = (
  params: CustomCellRendererProps & {
    valueRange?: ValueRange | null;
    alignPositiveNegative?: boolean;
    colorPositiveNegative?: boolean;
    basicColorFormatters?: TableChartTransformedProps['basicColorFormatters'];
    basicColorColumnFormatters?: TableChartTransformedProps['basicColorColumnFormatters'];
    sliceId: number;
  },
) => {
  const theme = useTheme();
  const {
    valueRange,
    alignPositiveNegative,
    colorPositiveNegative,
    basicColorFormatters,
    basicColorColumnFormatters,
    sliceId,
    column,
    colDef,
    node,
  } = params;

  const { value, valueFormatted } = getValueFromParams(params);

  const filters = useSelector(
    (state: RootState) => state.dataMask?.[sliceId]?.filterState?.filters,
  );

  const activeClassName =
    column && isActiveFilterValue(filters, column.getColId(), value)
      ? 'active-filter-cell'
      : '';

  if ((!valueRange && !basicColorFormatters) || node.level === -1) {
    return <div className={activeClassName}>{valueFormatted ?? value}</div>;
  }

  if (basicColorColumnFormatters || basicColorFormatters) {
    const originKey = colDef?.field
      ?.substring(colDef.headerName!.length)
      .trim();
    const formatter =
      basicColorColumnFormatters?.[node?.rowIndex ?? 0]?.[
        column?.getColId() || ''
      ] || basicColorFormatters?.[node?.rowIndex ?? 0]?.[originKey!];
    const arrow =
      colDef?.headerName === COMPARISON_LABELS[0] ? formatter?.mainArrow : '';
    const arrowStyles = css`
      color: ${formatter?.arrowColor === ColorSchemeEnum.Green
        ? theme.colors.success.base
        : theme.colors.error.base};
      margin-left: ${theme.sizeUnit}px;
    `;
    return (
      <div>
        {valueFormatted ?? value}
        <span css={arrowStyles}>{arrow}</span>
      </div>
    );
  }
  if (valueRange) {
    const cellWidth = `${getCellWidth(
      value,
      valueRange,
      alignPositiveNegative,
    )}%`;
    const cellOffset = `${getCellOffset(
      value,
      valueRange,
      alignPositiveNegative,
    )}%`;
    const cellBackground = getCellBackground(value, colorPositiveNegative);
    const cellBarStyles = css`
      position: absolute;
      height: 100%;
      display: block;
      top: 0;
      width: ${cellWidth};
      left: ${cellOffset};
      background-color: ${cellBackground};
    `;
    return (
      <div>
        <div className="cell-bar" css={cellBarStyles} />
        {valueFormatted ?? value}
      </div>
    );
  }
  return valueFormatted ?? value;
};
