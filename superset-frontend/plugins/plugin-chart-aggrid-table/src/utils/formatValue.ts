import {
  CurrencyFormatter,
  DataRecordValue,
  GenericDataType,
  getNumberFormatter,
  isDefined,
  isProbablyHTML,
  sanitizeHtml,
} from '@superset-ui/core';
import { ValueFormatterParams, ValueGetterParams } from 'ag-grid-community';
import DateWithFormatter from './DateWithFormatter';
import { TableDataColumnMeta } from '../types';

/**
 * Format text for cell value.
 */
function formatValue(
  formatter: any,
  value: DataRecordValue,
): [boolean, string] {
  // render undefined as empty string
  if (value === undefined) {
    return [false, ''];
  }
  // render null as `N/A`
  if (
    value === null ||
    // null values in temporal columns are wrapped in a Date object, so make sure we
    // handle them here too
    (value instanceof DateWithFormatter && value.input === null)
  ) {
    return [false, 'N/A'];
  }
  if (formatter) {
    return [false, formatter(value as number)];
  }
  if (typeof value === 'string') {
    return isProbablyHTML(value) ? [true, sanitizeHtml(value)] : [false, value];
  }
  return [false, value.toString()];
}

export function formatColumnValue(column: any, value: DataRecordValue) {
  const { dataType, formatter, config = {} } = column;
  const isNumber = dataType === GenericDataType.Numeric;
  const smallNumberFormatter =
    config.d3SmallNumberFormat === undefined
      ? formatter
      : config.currencyFormat
        ? new CurrencyFormatter({
            d3Format: config.d3SmallNumberFormat,
            currency: config.currencyFormat,
          })
        : getNumberFormatter(config.d3SmallNumberFormat);
  return formatValue(
    isNumber && typeof value === 'number' && Math.abs(value) < 1
      ? smallNumberFormatter
      : formatter,
    value,
  );
}

export const valueGetter = (
  params: ValueGetterParams,
  col: TableDataColumnMeta,
) => {
  if (isDefined(params.data?.[params.column.getColId()])) {
    return params.data[params.column.getColId()];
  }
  if (col.isNumeric) {
    return undefined;
  }
  return '';
};

export const valueFormatter = (
  params: ValueFormatterParams,
  col: TableDataColumnMeta,
) => {
  if (
    isDefined(params.value) &&
    params.value !== '' &&
    !(params.value instanceof DateWithFormatter && params.value.input === null)
  ) {
    return col.formatter?.(params.value) || params.value;
  }
  if (params.node?.level === -1) {
    return '';
  }
  return 'N/A';
};
