import { useMemo } from 'react';
import {
  CellClassParams,
  ColDef,
  ColGroupDef,
  GroupCellRendererParams,
  ValueFormatterParams,
} from 'ag-grid-community';
import {
  CurrencyFormatter,
  getColumnLabel,
  getMetricLabel,
  getNumberFormatter,
  isDefined,
} from '@superset-ui/core';
import { ColorFormatters } from '@superset-ui/chart-controls';
import { PivotTableProps } from '../types';
import { getVerboseMetricLabel } from './getVerboseMetricLabel';

const getCellStyle = (
  metricName: string,
  colorFormatters: ColorFormatters,
  params: CellClassParams,
) => {
  let styles = {};
  if (Array.isArray(colorFormatters) && colorFormatters.length > 0) {
    const formatters = colorFormatters.filter(
      colorFormatter => colorFormatter.column === metricName,
    );
    if (formatters) {
      let backgroundColor;
      formatters.forEach(formatter => {
        const bg = formatter.getColorFromValue(params.value);
        if (bg) {
          backgroundColor = bg;
        }
      });
      styles = {
        ...styles,
        backgroundColor,
      };
    }
  }
  return styles;
};

// TODO: autoHeight disabled due to AG Grid performance issues - reenable when fixed
export const defaultColDef: ColDef = {
  filter: true,
  flex: 1,
  minWidth: 100,
  wrapHeaderText: true,
  // autoHeaderHeight: true,
  // autoHeight: true,
  wrapText: true,
};

export const defaultColGroupDef: ColGroupDef = {
  marryChildren: true,
  // autoHeaderHeight: true,
  // wrapHeaderText: true,
  children: [],
};

export const autoGroupColumnDef = {
  cellRendererParams: {
    totalValueGetter: (params: GroupCellRendererParams) => {
      const isRootLevel = params.node.level === -1;
      if (isRootLevel) {
        return 'Summary';
      }
      return `Summary (${params.value})`;
    },
  },
};

export const useColDefs = ({
  groupby,
  metrics,
  verboseMap,
  metricColorFormatters,
  currencyFormat,
  valueFormat,
  dateFormatters,
  pivotTableState,
}: Pick<
  PivotTableProps,
  | 'groupby'
  | 'metrics'
  | 'verboseMap'
  | 'metricColorFormatters'
  | 'currencyFormat'
  | 'valueFormat'
  | 'dateFormatters'
  | 'pivotTableState'
>) => {
  const defaultFormatter = useMemo(
    () =>
      currencyFormat?.symbol
        ? new CurrencyFormatter({
            currency: currencyFormat,
            d3Format: valueFormat,
          })
        : getNumberFormatter(valueFormat),
    [valueFormat, currencyFormat],
  );
  return useMemo<ColDef[]>(
    () => [
      ...groupby.map(dimensionName => {
        const columnLabel = getColumnLabel(dimensionName);
        const initialRowGroup =
          pivotTableState?.rowGroup?.groupColIds.includes(columnLabel);
        const initialPivot = !initialRowGroup;
        return {
          field: columnLabel,
          headerName: verboseMap[columnLabel],
          valueFormatter: (params: ValueFormatterParams) =>
            dateFormatters[columnLabel]?.(params.value) ?? params.value,
          keyCreator: (params: ValueFormatterParams) =>
            dateFormatters[columnLabel]?.(params.value) ?? params.value,
          enableRowGroup: true,
          enablePivot: true,
          initialRowGroup,
          initialPivot,
        };
      }),
      ...metrics.map(metric => ({
        field: getMetricLabel(metric),
        headerName: getVerboseMetricLabel(metric, verboseMap),
        cellStyle: (params: CellClassParams) =>
          getCellStyle(getMetricLabel(metric), metricColorFormatters, params),
        defaultAggFunc: 'sum',
        initialAggFunc: 'sum',
        enableValue: true,
        valueFormatter: (params: ValueFormatterParams) =>
          !isDefined(params.value) ? '' : defaultFormatter(params.value),
      })),
    ],
    [
      groupby,
      metrics,
      verboseMap,
      metricColorFormatters,
      currencyFormat,
      valueFormat,
      dateFormatters,
      defaultFormatter,
    ],
  );
};
