import { DataRecordFilters, DataRecordValue } from '@superset-ui/core';

export const isActiveFilterValue = (
  filters: DataRecordFilters | undefined,
  key: string,
  val: DataRecordValue,
) => {
  if (val instanceof Date) {
    return (
      !!filters &&
      filters[key]?.some(
        filterVal =>
          filterVal instanceof Date && filterVal.getTime() === val.getTime(),
      )
    );
  }
  return !!filters && filters[key]?.includes(val);
};
