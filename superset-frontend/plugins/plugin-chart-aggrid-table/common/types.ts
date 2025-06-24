import {
  CurrencyFormatter,
  DataRecordValue,
  GenericDataType,
  NumberFormatter,
  TimeFormatter,
} from '@superset-ui/core';

export enum DrillSource {
  ROW = 'row',
  PIVOT = 'pivot',
}

export type CustomFormatter = (value: DataRecordValue) => string;

export interface DataColumnMeta {
  // `key` is what is called `label` in the input props
  key: string;
  // `label` is verbose column name used for rendering
  label: string;
  // `originalLabel` preserves the original label when time comparison transforms the labels
  originalLabel?: string;
  dataType: GenericDataType;
  formatter?:
    | TimeFormatter
    | NumberFormatter
    | CustomFormatter
    | CurrencyFormatter;
  isMetric?: boolean;
  isPercentMetric?: boolean;
  isNumeric?: boolean;
  isChildColumn?: boolean;
}
