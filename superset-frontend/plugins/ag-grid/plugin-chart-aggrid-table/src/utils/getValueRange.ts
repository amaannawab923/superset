import { extent as d3Extent, max as d3Max } from 'd3-array';
import {
  TableDataColumnMeta,
  TableChartTransformedProps,
  ValueRange,
} from '../types';

export const getValueRange = (
  data: TableChartTransformedProps['data'],
  col: TableDataColumnMeta,
  alignPositiveNegative?: boolean,
) => {
  if (col.isNumeric || typeof data?.[0]?.[col.key] === 'number') {
    const nums = data.map(row => row[col.key]) as number[];
    return (
      alignPositiveNegative ? [0, d3Max(nums.map(Math.abs))] : d3Extent(nums)
    ) as ValueRange;
  }
  return null;
};
