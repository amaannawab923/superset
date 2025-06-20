import {
  DataRecordFilters,
  DataRecordValue,
  DTTM_ALIAS,
  ensureIsArray,
  getTimeFormatterForGranularity,
  TimeGranularity,
} from '@superset-ui/core';
import { isActiveFilterValue } from '../../../common/utils/isActiveFilterValue';

const timestampFormatter = (
  timeGrain: TimeGranularity,
  value: number | Date | null | undefined,
) => getTimeFormatterForGranularity(timeGrain)(value);

export const getCrossFilterDataMask = (
  key: string,
  value: DataRecordValue,
  filters?: DataRecordFilters,
  timeGrain?: TimeGranularity,
) => {
  let updatedFilters = { ...(filters || {}) };
  if (filters && isActiveFilterValue(filters, key, value)) {
    updatedFilters = {};
  } else {
    updatedFilters = {
      [key]: [value],
    };
  }
  if (Array.isArray(updatedFilters[key]) && updatedFilters[key].length === 0) {
    delete updatedFilters[key];
  }

  const groupBy = Object.keys(updatedFilters);
  const groupByValues = Object.values(updatedFilters);
  const labelElements: string[] = [];
  groupBy.forEach(col => {
    const isTimestamp = col === DTTM_ALIAS;
    const filterValues = ensureIsArray(updatedFilters?.[col]);
    if (filterValues.length) {
      const valueLabels = filterValues.map(value =>
        isTimestamp && timeGrain
          ? timestampFormatter(
              timeGrain,
              value as number | Date | null | undefined,
            )
          : value,
      );
      labelElements.push(`${valueLabels.join(', ')}`);
    }
  });

  return {
    dataMask: {
      extraFormData: {
        filters:
          groupBy.length === 0
            ? []
            : groupBy.map(col => {
                const val = ensureIsArray(updatedFilters?.[col]);
                if (!val.length)
                  return {
                    col,
                    op: 'IS NULL' as const,
                  };
                return {
                  col,
                  op: 'IN' as const,
                  val: val.map(el => (el instanceof Date ? el.getTime() : el!)),
                  grain: col === DTTM_ALIAS ? timeGrain : undefined,
                };
              }),
      },
      filterState: {
        label: labelElements.join(', '),
        value: groupByValues.length ? groupByValues : null,
        filters:
          updatedFilters && Object.keys(updatedFilters).length
            ? updatedFilters
            : null,
      },
    },
    isCurrentValueSelected: isActiveFilterValue(filters, key, value),
  };
};
