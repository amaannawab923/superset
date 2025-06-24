import { IAggFuncParams } from 'ag-grid-community';
import { useMemo } from 'react';
import { TableChartTransformedProps } from '../types';
import { CUSTOM_AGG_FUNCS } from '../consts';

export const useCustomAggFuncs = (
  totals: TableChartTransformedProps['totals'],
) =>
  useMemo(
    () => ({
      [CUSTOM_AGG_FUNCS.queryTotal]: (params: IAggFuncParams) =>
        totals?.hasOwnProperty(params.column.getColId())
          ? totals[params.column.getColId()]
          : 0,
    }),
    [totals],
  );
