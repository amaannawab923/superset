import { TableDataColumnMeta } from '../types';
import { CUSTOM_AGG_FUNCS } from '../consts';

export const getAggFunc = (col: TableDataColumnMeta) =>
  col.isMetric || col.isPercentMetric
    ? CUSTOM_AGG_FUNCS.queryTotal
    : col.isNumeric
      ? 'sum'
      : undefined;
