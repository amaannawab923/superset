import { CellClassParams } from 'ag-grid-community';
import { SupersetTheme } from '@superset-ui/core';
import { TableDataColumnMeta, TableChartTransformedProps } from './types';
import DateWithFormatter from './utils/DateWithFormatter';

export const getCellStyle = (
  col: TableDataColumnMeta,
  columnColorFormatters:
    | NonNullable<TableChartTransformedProps['columnColorFormatters']>[number][]
    | undefined,
  basicColorFormatters: TableChartTransformedProps['basicColorFormatters'],
  basicColorColumnFormatters: TableChartTransformedProps['basicColorColumnFormatters'],
  params: CellClassParams,
  theme: SupersetTheme,
) => {
  let styles = {};
  if (col.isNumeric) {
    styles = { ...styles, textAlign: 'right' };
  }
  if (
    (!params.value && params.value !== 0) ||
    (params.value instanceof DateWithFormatter && params.value.input === null)
  ) {
    styles = { ...styles, color: theme.colors.grayscale.light1 };
  }
  if (columnColorFormatters) {
    let backgroundColor = '';
    if (basicColorColumnFormatters && basicColorColumnFormatters?.length > 0) {
      backgroundColor =
        basicColorColumnFormatters[params.rowIndex][col.key]?.backgroundColor;
    }
    if (!backgroundColor) {
      columnColorFormatters.forEach(colorFormatter => {
        const color = colorFormatter.getColorFromValue(params.value);
        if (color) {
          backgroundColor = color;
        }
      });
    }
    styles = {
      ...styles,
      backgroundColor,
    };
  } else if (basicColorFormatters) {
    const originKey = col.key.substring(col.label.length).trim();
    styles = {
      ...styles,
      backgroundColor:
        basicColorFormatters[params.rowIndex]?.[originKey]?.backgroundColor,
    };
  }
  if (col.config?.horizontalAlign) {
    styles = { ...styles, textAlign: col.config.horizontalAlign };
  }
  return styles;
};
