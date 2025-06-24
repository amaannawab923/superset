import { useCallback } from 'react';
import { ColumnMovedEvent, GridState } from 'ag-grid-community';
import { isDefined } from '@superset-ui/core';

export const useSyncColumnMove = (
  columnsOrder: GridState['columnOrder'],
  showTotals?: boolean,
) =>
  useCallback(
    (p: ColumnMovedEvent) => {
      if (
        showTotals &&
        (p.toIndex === 0 ||
          !isDefined(columnsOrder) ||
          columnsOrder.orderedColIds[0] === p.column?.getColId())
      ) {
        const totalsRow = p.api.getDisplayedRowAtIndex(
          p.api.getDisplayedRowCount() - 1,
        );
        p.api.redrawRows({
          rowNodes: totalsRow?.footer ? [totalsRow] : undefined,
        });
      }
    },
    [showTotals, columnsOrder],
  );
