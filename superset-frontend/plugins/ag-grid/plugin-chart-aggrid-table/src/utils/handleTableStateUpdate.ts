import { useMemo } from 'react';
import { GridState } from 'ag-grid-community';
import { getAggFunc } from './getAggFunc';
import { TableDataColumnMeta } from '../types';

export const useTableStateMemoized = (
  columns: TableDataColumnMeta[],
  tableState?: GridState,
) =>
  useMemo(() => {
    // workaround for ag-grid problem - when a new column is added, it is not present in the aggregation model
    // and for some reason the default defined in the column definition is not used
    // we need to add it back to the model or empty cells will be shown in the summary row
    if (tableState?.aggregation?.aggregationModel) {
      columns
        .filter(col => col.isNumeric)
        .forEach(col => {
          if (
            !tableState.aggregation!.aggregationModel.some(
              model => model.colId === col.key,
            )
          ) {
            tableState.aggregation!.aggregationModel.push({
              colId: col.key,
              aggFunc: getAggFunc(col) ?? 'sum',
            });
          }
        });
    }
    return tableState;
  }, []);
