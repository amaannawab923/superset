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
import { valueFormatter, valueGetter } from '../utils/formatValue';
import { NumericCellRenderer } from '../renderers/NumericCellRenderer';

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
  const colDefs: ColDef[] = columns.map((col, index, columns) => {
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
      valueGetter: p => valueGetter(p, col),
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
        filterValueGetter: params => {
          const raw = params.data[params.colDef.field as string];
          const formatter = params.colDef.valueFormatter as Function;
          if (!raw || !formatter) return null;
          const formatted = formatter({
            value: raw,
          });

          const numeric = parseFloat(String(formatted).replace('%', '').trim());
          return Number.isNaN(numeric) ? null : numeric;
        },
      }),
      ...(col?.dataType === GenericDataType.Temporal && {
        filterParams: {
          comparator: (filterDate: Date, cellValue: Date) => {
            const cellDate = new Date(cellValue);
            if (Number.isNaN(cellDate?.getTime())) return -1;

            const cellDay = cellDate.getDate();
            const cellMonth = cellDate.getMonth();
            const cellYear = cellDate.getFullYear();

            const filterDay = filterDate.getDate();
            const filterMonth = filterDate.getMonth();
            const filterYear = filterDate.getFullYear();

            if (cellYear < filterYear) return -1;
            if (cellYear > filterYear) return 1;
            if (cellMonth < filterMonth) return -1;
            if (cellMonth > filterMonth) return 1;
            if (cellDay < filterDay) return -1;
            if (cellDay > filterDay) return 1;

            return 0;
          },
        },
      }),

      minWidth: Math.max(
        calculateMinWidth(headerLabel),
        col?.config?.columnWidth || 0,
      ),
      customMeta: {
        isMetric: col?.isMetric,
        isPercentMetric: col?.isPercentMetric,
      },
      ...(!(col.isMetric || col.isPercentMetric) && {
        // don't allow 'Query total' aggregation for non-metric columns
        allowedAggFuncs: ['sum', 'min', 'max', 'count', 'avg', 'first', 'last'],
      }),
      cellStyle: params => {
        const { value, colDef, rowIndex } = params;
        let backgroundColor;
        if (hasColumnColorFormatters) {
          columnColorFormatters!
            .filter(formatter => {
              const colTitle = formatter?.column?.includes('Main')
                ? formatter?.column?.replace('Main', '').trim()
                : formatter?.column;
              return colTitle === colDef.field;
            })
            .forEach(formatter => {
              const formatterResult =
                value || value === 0
                  ? formatter.getColorFromValue(value)
                  : false;
              if (formatterResult) {
                backgroundColor = formatterResult;
              }
            });
        }

        if (hasBasicColorFormatters && col?.metricName) {
          backgroundColor =
            basicColorFormatters?.[rowIndex]?.[col.metricName]?.backgroundColor;
        }

        const textAlign =
          col?.config?.horizontalAlign || (col?.isNumeric ? 'right' : 'left');

        return {
          backgroundColor: backgroundColor || '',
          textAlign,
        };
      },

      lockPinned: !allowRearrangeColumns,

      cellClass: params => {
        const isActiveFilterValue = params?.context?.isActiveFilterValue;
        let className = '';
        if (emitCrossFilters) {
          if (!col?.isMetric) {
            className += ' dt-is-filter';
          }
          if (isActiveFilterValue?.(col?.key, params?.value)) {
            className += ' dt-is-active-filter';
          }
          if (col?.config?.truncateLongCells) {
            className += ' dt-truncate-cell';
          }
        }
        return className;
      },
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
