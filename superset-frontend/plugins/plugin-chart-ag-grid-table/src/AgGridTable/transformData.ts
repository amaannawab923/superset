/* eslint-disable camelcase */
/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

import { ColDef } from 'ag-grid-community';
import { extent as d3Extent, max as d3Max } from 'd3-array';
import { DataRecord, GenericDataType } from '@superset-ui/core';
import { ColorFormatters } from '@superset-ui/chart-controls';
import CustomHeader from './components/CustomHeader';
import { BasicColorFormatterType, CellRendererProps } from '../types';
import { TextCellRenderer } from '../renderers/TextCellRenderer';
import { valueFormatter } from '../utils/formatValue';
import { NumericCellRenderer } from '../renderers/NumericCellRenderer';
import filterValueGetter from '../utils/filterValueGetter';
import dateFilterComparator from '../utils/dateFilterComparator';
import getCellStyle from '../utils/getCellStyle';
import getCellClass from '../utils/getCellClass';

// Basically Col Defs of the Preset Table
export interface InputColumn {
  key: string;
  label: string;
  dataType: number;
  isNumeric: boolean;
  isMetric: boolean;
  isPercentMetric: boolean;
  config: Record<string, any>;
  formatter?: Function;
  originalLabel?: string;
  metricName?: string;
}

interface InputData {
  [key: string]: any;
}

type ValueRange = [number, number];

function renameMainKeys(data: Record<string, any>[]): Record<string, any>[] {
  return data.map(row => {
    const newRow: Record<string, any> = {};
    for (const key in row) {
      if (key.startsWith('Main ')) {
        const newKey = key.replace('Main ', '');
        newRow[newKey] = row[key];
      } else {
        newRow[key] = row[key];
      }
    }
    return newRow;
  });
}

function cleanTotals(totals: DataRecord) {
  const cleaned: DataRecord = {};

  for (const [key, value] of Object.entries(totals)) {
    if (key.includes('index')) {
      continue;
    }
    if (key.includes('Main')) {
      const newKey = key.replace('Main ', '');
      cleaned[newKey] = value;
    } else {
      cleaned[key] = value;
    }
  }

  return cleaned;
}

function getValueRange(
  key: string,
  alignPositiveNegative: boolean,
  data: InputData[],
) {
  if (typeof data?.[0]?.[key] === 'number') {
    const nums = data.map(row => row[key]) as number[];
    return (
      alignPositiveNegative ? [0, d3Max(nums.map(Math.abs))] : d3Extent(nums)
    ) as ValueRange;
  }
  return null;
}

function calculateMinWidth(headerName: string): number {
  const charCount = headerName.length === 1 ? 4 : headerName.length;
  const baseWidth = charCount * 8 + 32;
  return Math.max(baseWidth, 100);
}

function getHeaderLabel(col: InputColumn) {
  let headerLabel: string | undefined;

  const hasOriginalLabel = !!col?.originalLabel;
  const isMain = col?.key?.includes('Main');
  const hasDisplayTypeIcon = col?.config?.displayTypeIcon !== false;
  const hasCustomColumnName = !!col?.config?.customColumnName;

  if (hasOriginalLabel && hasCustomColumnName) {
    if ('displayTypeIcon' in col.config) {
      headerLabel =
        hasDisplayTypeIcon && !isMain
          ? `${col.label} ${col.config.customColumnName}`
          : col.config.customColumnName;
    } else {
      headerLabel = col.config.customColumnName;
    }
  } else if (hasOriginalLabel && isMain) {
    headerLabel = col.originalLabel;
  } else if (hasOriginalLabel && !hasDisplayTypeIcon) {
    headerLabel = '';
  } else {
    headerLabel = col?.label;
  }
  return headerLabel || '';
}

export const transformData = (
  columns: InputColumn[],
  data: InputData[],
  serverPagination: boolean,
  isRawRecords: boolean,
  defaultAlignPN: boolean,
  showCellBars: boolean,
  colorPositiveNegative: boolean,
  totals: DataRecord | undefined,
  columnColorFormatters: ColorFormatters,
  allowRearrangeColumns?: boolean,
  basicColorFormatters?: { [Key: string]: BasicColorFormatterType }[],
  isUsingTimeComparison?: boolean,
  emitCrossFilters?: boolean,
) => {
  const cleanedTotals = cleanTotals(totals || {});
  const colDefs: ColDef[] = columns.map((col, _, columns) => {
    const { config, isMetric, isPercentMetric, isNumeric } = col;
    const alignPositiveNegative =
      config.alignPositiveNegative === undefined
        ? defaultAlignPN
        : config.alignPositiveNegative;

    const hasColumnColorFormatters =
      isNumeric &&
      Array.isArray(columnColorFormatters) &&
      columnColorFormatters.length > 0;

    const hasBasicColorFormatters =
      isUsingTimeComparison &&
      Array.isArray(basicColorFormatters) &&
      basicColorFormatters.length > 0;

    const valueRange =
      !hasBasicColorFormatters &&
      !hasColumnColorFormatters &&
      showCellBars &&
      (config.showCellBars || config.showCellBars === undefined) &&
      (isMetric || isRawRecords || isPercentMetric) &&
      getValueRange(col.key, alignPositiveNegative, data);

    const colId = col?.key.includes('Main')
      ? col?.key.replace('Main', '').trim()
      : col?.key;
    const isTextColumn =
      col?.dataType === GenericDataType.String ||
      col?.dataType === GenericDataType.Temporal;

    const headerLabel = getHeaderLabel(col);

    return {
      field: colId,
      headerName: headerLabel,
      valueFormatter: p => valueFormatter(p, col),
      cellRenderer: (p: CellRendererProps) =>
        isTextColumn ? TextCellRenderer(p) : NumericCellRenderer(p),
      cellRendererParams: {
        allowRenderHtml: true,
        columns,
        hasBasicColorFormatters,
        col,
        basicColorFormatters,
        valueRange,
        alignPositiveNegative,
        colorPositiveNegative,
      },
      ...(isPercentMetric && {
        filterValueGetter,
      }),
      ...(col?.dataType === GenericDataType.Temporal && {
        filterParams: {
          comparator: dateFilterComparator,
        },
      }),
      minWidth: col.config?.columnWidth ?? 100,

      customMeta: {
        isMetric: col?.isMetric,
        isPercentMetric: col?.isPercentMetric,
      },
      ...(!(col.isMetric || col.isPercentMetric) && {
        // don't allow 'Query total' aggregation for non-metric columns
        allowedAggFuncs: ['sum', 'min', 'max', 'count', 'avg', 'first', 'last'],
      }),
      cellStyle: p =>
        getCellStyle({
          ...p,
          hasColumnColorFormatters,
          columnColorFormatters,
          hasBasicColorFormatters,
          basicColorFormatters,
          col,
        }),
      lockPinned: !allowRearrangeColumns,
      cellClass: p =>
        getCellClass({
          ...p,
          col,
          emitCrossFilters,
        }),
      sortable: !serverPagination || !col?.isPercentMetric,
      ...(serverPagination && {
        headerComponent: CustomHeader,
      }),
      filter: true,
      ...(serverPagination && {
        comparator: () => 0,
      }),
      ...(col?.originalLabel && {
        timeComparisonKey: col?.originalLabel,
        ...(col?.key &&
          col?.key.includes('Main') && {
            isMain: true,
          }),
      }),
      wrapText: !col.config?.truncateLongCells,
      autoHeight: !col.config?.truncateLongCells,
      // Add number specific properties for numeric columns
      ...(col.isNumeric && {
        type: 'rightAligned',
        filter: 'agNumberColumnFilter',
        cellDataType: 'number',
      }),
      aggFunc: 'sum',
    };
  });

  // Default column definition
  const defaultColDef = {
    flex: 1,
    filter: true,
    enableRowGroup: true,
    enableValue: true,
    sortable: true,
    resizable: true,
    minWidth: 100,
  };

  return {
    rowData: renameMainKeys(data),
    colDefs,
    defaultColDef,
    cleanedTotals,
  };
};
