import { useCallback, useMemo } from 'react';
import { ColDef, ColGroupDef } from 'ag-grid-community';
import { GenericDataType, useTheme } from '@superset-ui/core';
import { TableDataColumnMeta, TableChartTransformedProps } from '../types';
import { getValueRange } from './getValueRange';
import { valueFormatter, valueGetter } from './formatValue';
import { getAggFunc } from './getAggFunc';
import { dateFilterComparator } from './dateFilterComparator';
import { getCellStyle } from '../styles';
import { NumericCellRenderer } from '../renderers/NumericCellRenderer';
import { TextCellRenderer } from '../renderers/TextCellRenderer';
import { COMPARISON_LABELS } from '../consts';

export const defaultColDefs: ColDef = {
  filter: true,
  wrapHeaderText: true,
  autoHeaderHeight: true,
  autoHeight: true,
  flex: 1,
};

export const defaultColGroupDefs: ColGroupDef = {
  autoHeaderHeight: true,
  wrapHeaderText: true,
  marryChildren: true,
  openByDefault: true,
  children: [],
};

const getFilterType = (
  col: TableDataColumnMeta,
  includeSearch: boolean | undefined,
) => {
  if (!includeSearch) {
    return false;
  }
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

const getCellDataType = (col: TableDataColumnMeta) => {
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

export const useColDefs = ({
  columns,
  data,
  columnColorFormatters,
  basicColorFormatters,
  basicColorColumnFormatters,
  showCellBars,
  allowRenderHtml,
  isUsingTimeComparison,
  alignPositiveNegative,
  colorPositiveNegative,
  isRawRecords,
  sliceId,
  isDashboard,
  width,
  includeSearch,
}: Pick<
  TableChartTransformedProps,
  | 'columns'
  | 'data'
  | 'columnColorFormatters'
  | 'basicColorFormatters'
  | 'basicColorColumnFormatters'
  | 'totals'
  | 'showCellBars'
  | 'allowRenderHtml'
  | 'isUsingTimeComparison'
  | 'alignPositiveNegative'
  | 'colorPositiveNegative'
  | 'isRawRecords'
  | 'width'
  | 'includeSearch'
> & { sliceId: number; isDashboard: boolean }) => {
  const theme = useTheme();

  const hasBasicColorFormatters =
    isUsingTimeComparison &&
    Array.isArray(basicColorFormatters) &&
    basicColorFormatters.length > 0;

  // to be used in the useCallback dependency array
  const stringifiedCols = JSON.stringify(columns);
  const getCommonColProps = useCallback(
    (col: TableDataColumnMeta): ColDef => {
      const filter = getFilterType(col, includeSearch);
      const hasColumnColorFormatters =
        col.isNumeric &&
        Array.isArray(columnColorFormatters) &&
        columnColorFormatters.length > 0;

      const valueRange = getValueRange(
        data,
        col,
        col.config?.alignPositiveNegative || alignPositiveNegative,
      );
      return {
        field: col.key,
        headerName: col.label,
        valueFormatter: p => valueFormatter(p, col),
        valueGetter: p => valueGetter(p, col),
        cellStyle: params =>
          getCellStyle(
            col,
            hasColumnColorFormatters
              ? columnColorFormatters?.filter(
                  colorFormatter => colorFormatter.column === col.key,
                )
              : undefined,
            hasBasicColorFormatters ? basicColorFormatters : undefined,
            basicColorColumnFormatters,
            params,
            theme,
          ),
        minWidth: col.config?.columnWidth ?? 100,
        filter,
        ...(col.dataType === GenericDataType.Temporal && {
          filterParams: dateFilterComparator,
        }),
        cellDataType: getCellDataType(col),
        defaultAggFunc: getAggFunc(col),
        initialAggFunc: getAggFunc(col),
        ...(!(col.isMetric || col.isPercentMetric) && {
          // don't allow 'Query total' aggregation for non-metric columns
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
        ...((col.isMetric ||
          col.isPercentMetric ||
          (col.isNumeric && isRawRecords)) &&
          (showCellBars ||
            hasBasicColorFormatters ||
            col.config?.showCellBars ||
            basicColorColumnFormatters?.[0]?.[col.key]) &&
          (!hasColumnColorFormatters ||
            basicColorColumnFormatters?.[0]?.[col.key]) && {
            cellRenderer: NumericCellRenderer,
            cellRendererParams: {
              valueRange,
              alignPositiveNegative:
                col.config?.alignPositiveNegative || alignPositiveNegative,
              colorPositiveNegative:
                col.config?.colorPositiveNegative || colorPositiveNegative,
              basicColorFormatters: hasBasicColorFormatters
                ? basicColorFormatters
                : undefined,
              basicColorColumnFormatters,
            },
          }),
        ...((col.dataType === GenericDataType.String ||
          col.dataType === GenericDataType.Temporal) && {
          cellRenderer: TextCellRenderer,
          cellRendererParams: {
            allowRenderHtml,
            sliceId,
          },
        }),
        cellClass: params =>
          !col.isMetric &&
          !col.isPercentMetric &&
          params.node?.level !== -1 &&
          isDashboard
            ? 'non-metric-cell'
            : undefined,
        context: {
          isMetric: col.isMetric,
          isPercentMetric: col.isPercentMetric,
          isNumeric: col.isNumeric,
        },
        wrapText: !col.config?.truncateLongCells,
        autoHeight: !col.config?.truncateLongCells,
      };
    },
    [
      data,
      stringifiedCols,
      columnColorFormatters,
      JSON.stringify(basicColorFormatters),
      JSON.stringify(basicColorColumnFormatters),
      showCellBars,
      allowRenderHtml,
      alignPositiveNegative,
      colorPositiveNegative,
      isUsingTimeComparison,
      includeSearch,
      width,
    ],
  );
  return useMemo(() => {
    if (isUsingTimeComparison) {
      return columns.reduce(
        (acc, col) => {
          if (col.isMetric || col.isPercentMetric) {
            if (
              COMPARISON_LABELS.some(label => col.key.startsWith(`${label} `))
            ) {
              const [label, ...rest] = col.key.split(' ');
              const groupHeaderNameKey = rest.join(' ');
              const groupHeaderName = col.originalLabel || groupHeaderNameKey;

              const group = acc.find(
                colGroup => colGroup.headerName === groupHeaderName,
              ) as ColGroupDef;
              const config: ColDef = {
                ...getCommonColProps(col),
                headerName: label,
                columnGroupShow:
                  label === COMPARISON_LABELS[0]
                    ? undefined
                    : ('open' as const),
                minWidth: col.config?.columnWidth ?? 80,
              };
              if (!group) {
                acc.push({
                  headerName: groupHeaderName,
                  children: [config],
                } as ColGroupDef);
              } else {
                group.children.push(config);
              }
            }
          } else {
            acc.push(getCommonColProps(col));
          }
          return acc;
        },
        [] as (ColDef | ColGroupDef)[],
      );
    }
    return columns.map(col => getCommonColProps(col));
  }, [stringifiedCols, getCommonColProps]);
};
