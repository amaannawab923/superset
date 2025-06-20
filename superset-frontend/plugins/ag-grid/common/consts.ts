import { GridState } from 'ag-grid-community';
import { t } from '@superset-ui/core';

// TODO: enable column sizing persistence when persisting the column size actually works
export const STATE_FIELDS_TO_PERSIST: (keyof GridState)[] = [
  'columnOrder',
  'columnPinning',
  'filter',
  'sort',
  'pagination',
  'pivot',
  'rowGroup',
  'aggregation',
];

export const PERSISTED_FIELDS_LABELS = {
  columnOrder: t('Column order'),
  columnPinning: t('Pinned columns'),
  columnSizing: t('Column sizing'),
  filter: t('Filter'),
  sort: t('Column sorting'),
  pagination: t('Page size'),
  aggregation: t('Aggregation'),
  pivot: t('Pivot state'),
  rowGroup: t('Pivot state'),
};
