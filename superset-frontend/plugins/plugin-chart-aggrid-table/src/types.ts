import {
  TimeGranularity,
  QueryFormMetric,
  ChartProps,
  DataRecord,
  DataRecordFilters,
  QueryMode,
  ChartDataResponseResult,
  QueryFormData,
  SetDataMaskHook,
  ContextMenuFilters,
  Currency,
} from '@superset-ui/core';
import { ColorFormatters } from '@superset-ui/chart-controls';
import { GridState } from 'ag-grid-community';
// @ts-ignore
import { DataColumnMeta } from '../common/types';

export type TableColumnConfig = {
  d3NumberFormat?: string;
  d3SmallNumberFormat?: string;
  d3TimeFormat?: string;
  columnWidth?: number;
  horizontalAlign?: 'left' | 'right' | 'center';
  showCellBars?: boolean;
  alignPositiveNegative?: boolean;
  colorPositiveNegative?: boolean;
  truncateLongCells?: boolean;
  currencyFormat?: Currency;
};

export interface TableChartData {
  records: DataRecord[];
  columns: string[];
}

export type TableChartFormData = QueryFormData & {
  align_pn?: boolean;
  color_pn?: boolean;
  include_time?: boolean;
  include_search?: boolean;
  show_raw_record_totals?: boolean;
  query_mode?: QueryMode;
  page_length?: string | number | null; // null means auto-paginate
  metrics?: QueryFormMetric[] | null;
  percent_metrics?: QueryFormMetric[] | null;
  timeseries_limit_metric?: QueryFormMetric[] | QueryFormMetric | null;
  groupby?: QueryFormMetric[] | null;
  all_columns?: QueryFormMetric[] | null;
  order_desc?: boolean;
  show_cell_bars?: boolean;
  table_timestamp_format?: string;
  time_grain_sqla?: TimeGranularity;
  column_config?: Record<string, TableColumnConfig>;
  allow_rearrange_columns?: boolean;
};

export interface TableChartProps extends ChartProps {
  ownCurrentState?: {
    pageSize?: number;
    currentPage?: number;
  };
  rawFormData: TableChartFormData;
  queriesData: ChartDataResponseResult[];
}

export type BasicColorFormatterType = {
  backgroundColor: string;
  arrowColor: string;
  mainArrow: string;
};

export type TableDataColumnMeta = DataColumnMeta & {
  config?: TableColumnConfig;
};

export interface TableChartTransformedProps<D extends DataRecord = DataRecord> {
  timeGrain?: TimeGranularity;
  height: number;
  width: number;
  rowCount?: number;
  setDataMask: SetDataMaskHook;
  setControlValue: (key: string, value: any) => void;
  isRawRecords?: boolean;
  data: D[];
  totals?: D;
  columns: TableDataColumnMeta[];
  metrics?: (keyof D)[];
  percentMetrics?: (keyof D)[];
  pageSize?: number;
  showCellBars?: boolean;
  sortDesc?: boolean;
  includeSearch?: boolean;
  alignPositiveNegative?: boolean;
  colorPositiveNegative?: boolean;
  tableTimestampFormat?: string;
  showRawRecordTotals?: boolean;
  // These are dashboard filters, don't be confused with in-chart search filter
  // enabled by `includeSearch`
  filters?: DataRecordFilters;
  emitCrossFilters?: boolean;
  onChangeFilter?: ChartProps['hooks']['onAddFilter'];
  columnColorFormatters?: ColorFormatters;
  allowRearrangeColumns?: boolean;
  allowRenderHtml?: boolean;
  onContextMenu?: (
    clientX: number,
    clientY: number,
    filters?: ContextMenuFilters,
  ) => void;
  isUsingTimeComparison?: boolean;
  basicColorFormatters?: { [Key: string]: BasicColorFormatterType }[];
  basicColorColumnFormatters?: { [Key: string]: BasicColorFormatterType }[];
  startDateOffset?: string;
  tableState?: GridState;
  formData: TableChartFormData;
}

export enum ColorSchemeEnum {
  'Green' = 'Green',
  'Red' = 'Red',
}

export type ValueRange = [number, number];

export const isSimpleValue = (
  val: number | string | null | undefined | { value: number | string },
): val is number | string | null | undefined =>
  typeof val === 'number' ||
  typeof val === 'string' ||
  typeof val === 'undefined' ||
  val === null;

export default {};
