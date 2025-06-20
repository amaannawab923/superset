import { useContext, useCallback, useMemo, memo, useState } from 'react';
import { AgGridReact } from 'ag-grid-react';
import {
  CellClickedEvent,
  IMenuActionParams,
  GetMainMenuItems,
} from 'ag-grid-community';
import { BinaryQueryObjectFilterClause, Column } from '@superset-ui/core';
import { DashboardPageIdContext } from 'src/dashboard/containers/DashboardPage';
import DrillDetailModal from 'src/components/Chart/DrillDetail/DrillDetailModal';
import { Dataset } from 'src/components/Chart/types';
import DrillByModal from '../../common/drillBy/DrillByModal';
import { TableChartTransformedProps } from './types';
import { getCrossFilterDataMask } from './utils/getCrossFilterDataMask';
import {
  defaultColDefs,
  defaultColGroupDefs,
  useColDefs,
} from './utils/useColDefs';
import { autoSizeStrategy, PAGE_SIZE_OPTIONS } from './consts';
import { useGetContextMenuItems } from './utils/useGetContextMenuItems';
import { useTableStateMemoized } from './utils/handleTableStateUpdate';
import { useCustomAggFuncs } from './utils/useCustomAggFuncs';
import { useSyncColumnMove } from './utils/useSyncColumnMove';
import { StyledContainer, usePresetTheme } from '../../common/styles';
import { useTableStateUpdate } from '../../common/utils/useTableStateUpdate';

const TableChart = ({
  data,
  columns,
  isUsingTimeComparison,
  totals,
  columnColorFormatters,
  basicColorFormatters,
  basicColorColumnFormatters,
  height,
  width,
  emitCrossFilters,
  setDataMask,
  filters,
  timeGrain,
  showCellBars,
  allowRenderHtml,
  alignPositiveNegative,
  colorPositiveNegative,
  setControlValue,
  tableState,
  isRawRecords,
  includeSearch,
  formData,
  showRawRecordTotals,
}: TableChartTransformedProps) => {
  const dashboardPageId = useContext(DashboardPageIdContext);
  const [drillToDetailFilters, setDrillToDetailFilters] = useState<
    BinaryQueryObjectFilterClause[] | undefined
  >(undefined);
  const [drillByModalProps, setDrillByModalProps] = useState<{
    column: Column;
    dataset: Dataset;
    canDownload: boolean;
    onHideModal: () => void;
    drillByConfig: {
      filters: BinaryQueryObjectFilterClause[];
      groupbyFieldName: string;
      adhocFilterFieldName?: string;
    };
  } | null>(null);

  const presetTheme = usePresetTheme();
  const rowData = useMemo(() => data, [data]);
  const colDefs = useColDefs({
    columns,
    data: rowData,
    columnColorFormatters,
    basicColorFormatters,
    basicColorColumnFormatters,
    totals,
    showCellBars,
    allowRenderHtml,
    isUsingTimeComparison,
    alignPositiveNegative,
    colorPositiveNegative,
    isRawRecords,
    sliceId: formData.slice_id,
    isDashboard: !!dashboardPageId,
    width,
    includeSearch,
  });

  const containerStyles = useMemo(
    () => ({
      height,
      width,
    }),
    [height, width],
  );

  const toggleFilter = useCallback(
    (event: CellClickedEvent | IMenuActionParams) => {
      if (
        emitCrossFilters &&
        event.column &&
        !(
          event.column.getColDef().context?.isMetric ||
          event.column.getColDef().context?.isPercentMetric
        )
      ) {
        setDataMask(
          getCrossFilterDataMask(
            event.column.getColId(),
            event.value,
            filters,
            timeGrain,
          ).dataMask,
        );
      }
    },
    [emitCrossFilters, setDataMask, filters, timeGrain],
  );

  const handleTableStateUpdate = useTableStateUpdate(
    setControlValue,
    columns,
    dashboardPageId,
    tableState?.pagination?.pageSize,
  );

  const getContextMenuItems = useGetContextMenuItems(
    formData,
    columns,
    filters,
    toggleFilter,
    setDrillToDetailFilters,
    formData.drillByAdditionalConfig || { onSelection: setDrillByModalProps },
    emitCrossFilters,
    isRawRecords,
    dashboardPageId,
  );

  const tableStateMemoized = useTableStateMemoized(columns, tableState);

  const customAggFuncs = useCustomAggFuncs(totals);

  const showTotals = useMemo(
    () =>
      (isRawRecords &&
        showRawRecordTotals &&
        columns.some(col => col.isNumeric)) ||
      (!isRawRecords && !!totals),
    [isRawRecords, showRawRecordTotals, columns, totals],
  );

  const getMainMenuItems: GetMainMenuItems = useCallback(
    params =>
      params.column?.getColDef().context?.isNumeric && showTotals
        ? ['valueAggSubMenu', ...params.defaultItems]
        : params.defaultItems,
    [columns, showTotals],
  );

  const onColumnMoved = useSyncColumnMove(tableState?.columnOrder, showTotals);

  return (
    <StyledContainer style={containerStyles}>
      <AgGridReact
        theme={presetTheme}
        defaultColDef={defaultColDefs}
        defaultColGroupDef={defaultColGroupDefs}
        rowData={rowData}
        columnDefs={colDefs}
        autoSizeStrategy={autoSizeStrategy}
        pagination
        paginationPageSizeSelector={PAGE_SIZE_OPTIONS}
        grandTotalRow={showTotals ? 'bottom' : undefined}
        onCellClicked={toggleFilter}
        cellSelection
        suppressRowHoverHighlight
        onStateUpdated={handleTableStateUpdate}
        initialState={tableStateMemoized}
        getContextMenuItems={getContextMenuItems}
        getMainMenuItems={getMainMenuItems}
        maintainColumnOrder
        suppressDragLeaveHidesColumns
        suppressAggFuncInHeader
        aggFuncs={customAggFuncs}
        onColumnMoved={onColumnMoved}
      />
      {drillToDetailFilters && (
        <DrillDetailModal
          chartId={formData.slice_id}
          formData={formData}
          initialFilters={drillToDetailFilters}
          showModal={!!drillToDetailFilters}
          onHideModal={() => setDrillToDetailFilters(undefined)}
        />
      )}
      {drillByModalProps && !formData.drillByAdditionalConfig && (
        <DrillByModal
          {...drillByModalProps}
          formData={formData}
          dashboardPageId={dashboardPageId}
        />
      )}
    </StyledContainer>
  );
};

export default memo(TableChart);
