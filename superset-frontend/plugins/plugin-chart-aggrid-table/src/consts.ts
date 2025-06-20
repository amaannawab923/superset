import { t } from '@superset-ui/core';
import { SizeColumnsToFitGridStrategy } from 'ag-grid-community';

export const PAGE_SIZE_OPTIONS = [10, 20, 50, 100, 200];

export const COMPARISON_LABELS = [t('Main'), '#', '△', '%'];

export const CUSTOM_AGG_FUNCS = {
  queryTotal: 'Metric total',
};

export const autoSizeStrategy: SizeColumnsToFitGridStrategy = {
  type: 'fitGridWidth',
};
