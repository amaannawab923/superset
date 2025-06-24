import { isDefined, t } from '@superset-ui/core';
import { StateUpdatedEvent } from 'ag-grid-community';
import { pick } from 'lodash';
import { useCallback, useRef } from 'react';
import { useToasts } from 'src/components/MessageToasts/withToasts';
// @ts-ignore
import { PERSISTED_FIELDS_LABELS, STATE_FIELDS_TO_PERSIST } from '../consts';
import { DataColumnMeta } from '../types';

export const useTableStateUpdate = (
  setControlValue: (key: string, value: any) => void,
  columns: DataColumnMeta[],
  dashboardPageId: string,
  pageSize: number | undefined,
  tableStateControlName = 'table_state',
) => {
  const { addInfoToast } = useToasts();
  const toastsDisplayedRef = useRef<Record<string, boolean>>({});
  return useCallback(
    (event: StateUpdatedEvent) => {
      if (
        dashboardPageId ||
        !event.sources.some(source =>
          // @ts-ignore
          STATE_FIELDS_TO_PERSIST.includes(source),
        ) ||
        event.sources.includes('gridInitializing')
      ) {
        return;
      }

      // don't persist pagination if only the current page changed
      if (
        event.sources.includes('pagination') &&
        pageSize === event.state.pagination?.pageSize
      ) {
        return;
      }
      // workaround for ag-grid problem - when user chooses aggregation None, it gets removed from the model
      // we need to add it back to the model or it won't be persisted and a fallback will be used on next load
      if (event.sources.includes('aggregation')) {
        columns
          .filter(
            col =>
              !event.state?.aggregation?.aggregationModel.some(
                m => m.colId === col.key,
              ),
          )
          .forEach(col => {
            event.state?.aggregation?.aggregationModel.push({
              colId: col.key,
              aggFunc: 'none',
            });
          });
      }
      const stateToPersist = pick(event.state, STATE_FIELDS_TO_PERSIST);
      if (isDefined(stateToPersist.pagination)) {
        stateToPersist.pagination.page = 0;
      }
      if (!toastsDisplayedRef.current[event.sources[0]]) {
        const source =
          // @ts-ignore
          PERSISTED_FIELDS_LABELS[event.sources[0]] || t('Table state');
        addInfoToast(`${source} will be retained when you save the chart.`, {
          noDuplicate: true,
        });
        toastsDisplayedRef.current[event.sources[0]] = true;
      }
      stateToPersist.partialColumnState = true;
      setControlValue(tableStateControlName, stateToPersist);
    },
    [setControlValue, pageSize, addInfoToast],
  );
};
