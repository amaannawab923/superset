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
import { useCallback } from 'react';
import CustomHeader from './components/CustomHeader';
import { BasicColorFormatterType, CellRendererProps } from '../types';
import { TextCellRenderer } from '../renderers/TextCellRenderer';
import { valueFormatter, valueGetter } from '../utils/formatValue';
import { NumericCellRenderer } from '../renderers/NumericCellRenderer';
import filterValueGetter from '../utils/filterValueGetter';
import dateFilterComparator from '../utils/dateFilterComparator';
import getCellStyle from '../utils/getCellStyle';
import getCellClass from '../utils/getCellClass';
import { getAggFunc } from '../utils/getAggFunc';

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

const getCellDataType = (col: InputColumn) => {
  switch (col.dataType) {
    case GenericDataType.Numeric:
      return 'number';
    case GenericDataType.Temporal:
      return 'date';
    case GenericDataType.Boolean:
      return 'boolean';
    default:
      return 'text';
  }
};

const getFilterType = (col: InputColumn) => {
  switch (col.dataType) {
    case GenericDataType.Numeric:
      return 'agNumberColumnFilter';
    case GenericDataType.String:
      return 'agMultiColumnFilter';
    case GenericDataType.Temporal:
      return 'agDateColumnFilter';
    default:
      return true;
  }
};

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

export const useTransformData = (
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

  const getAdvancedColProps = useCallback(
    (
      col: InputColumn,
    ): ColDef & {
      isMain: boolean;
      customMeta: {
        isNumeric: boolean | undefined;
        isPercentMetric: boolean | undefined;
        isMetric: boolean | undefined;
      };
    } => {
      const {
        config,
        isMetric,
        isPercentMetric,
        isNumeric,
        key: originalKey,
        dataType,
        originalLabel,
      } = col;

      const alignPN =
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

      const isMain = originalKey?.includes('Main');
      const colId = isMain
        ? originalKey.replace('Main', '').trim()
        : originalKey;
      const isTextColumn =
        dataType === GenericDataType.String ||
        dataType === GenericDataType.Temporal;

      const valueRange =
        !hasBasicColorFormatters &&
        !hasColumnColorFormatters &&
        showCellBars &&
        (config.showCellBars ?? true) &&
        (isMetric || isRawRecords || isPercentMetric) &&
        getValueRange(colId, alignPN, data);

      const filter = getFilterType(col);

      return {
        field: colId,
        headerName: getHeaderLabel(col),
        valueFormatter: p => valueFormatter(p, col),
        valueGetter: p => valueGetter(p, col),
        cellStyle: p =>
          getCellStyle({
            ...p,
            hasColumnColorFormatters,
            columnColorFormatters,
            hasBasicColorFormatters,
            basicColorFormatters,
            col,
          }),
        cellClass: p =>
          getCellClass({
            ...p,
            col,
            emitCrossFilters,
          }),
        minWidth: config?.columnWidth ?? 100,
        filter,
        ...(isPercentMetric && {
          filterValueGetter,
        }),
        ...(dataType === GenericDataType.Temporal && {
          filterParams: {
            comparator: dateFilterComparator,
          },
        }),
        cellDataType: getCellDataType(col),
        defaultAggFunc: getAggFunc(col),
        initialAggFunc: getAggFunc(col),
        ...(!(isMetric || isPercentMetric) && {
          allowedAggFuncs: [
            'sum',
            'min',
            'max',
            'count',
            'avg',
            'first',
            'last',
          ],
        }),
        cellRenderer: (p: CellRendererProps) =>
          isTextColumn ? TextCellRenderer(p) : NumericCellRenderer(p),
        cellRendererParams: {
          allowRenderHtml: true,
          columns,
          hasBasicColorFormatters,
          col,
          basicColorFormatters,
          valueRange,
          alignPositiveNegative: alignPN,
          colorPositiveNegative,
        },
        customMeta: {
          isMetric,
          isPercentMetric,
          isNumeric,
        },
        lockPinned: !allowRearrangeColumns,
        sortable: !serverPagination || !isPercentMetric,
        ...(serverPagination && {
          headerComponent: CustomHeader,
          comparator: () => 0,
        }),
        isMain,
        ...(originalLabel && {
          timeComparisonKey: originalLabel,
        }),
        wrapText: !config?.truncateLongCells,
      };
    },
    [
      columns,
      data,
      defaultAlignPN,
      columnColorFormatters,
      basicColorFormatters,
      showCellBars,
      colorPositiveNegative,
      isUsingTimeComparison,
      isRawRecords,
      emitCrossFilters,
      allowRearrangeColumns,
      serverPagination,
    ],
  );

  const colDefs: ColDef[] = columns.map(col => getAdvancedColProps(col));

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
