import { CUSTOM_AGG_FUNCS } from '../consts';
import { InputColumn } from '../AgGridTable/transformData';

export const getAggFunc = (col: InputColumn) =>
  col.isMetric || col.isPercentMetric
    ? CUSTOM_AGG_FUNCS.queryTotal
    : col.isNumeric
      ? 'sum'
      : undefined;
