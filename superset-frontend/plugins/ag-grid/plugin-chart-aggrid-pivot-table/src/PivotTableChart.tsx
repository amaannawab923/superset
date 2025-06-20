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

import { useCallback, useContext, useMemo, useRef, useState } from 'react';
import { AgGridReact } from 'ag-grid-react';
import {
  CellClickedEvent,
  ColDef,
  GetContextMenuItems,
  GetMainMenuItems,
  GridColumnsChangedEvent,
  GridReadyEvent,
  SideBarDef,
} from 'ag-grid-community';
import { BinaryQueryObjectFilterClause, Column } from '@superset-ui/core';
import { Dataset } from 'src/components/Chart/types';
import DrillDetailModal from 'src/components/Chart/DrillDetail/DrillDetailModal';
import { DashboardPageIdContext } from 'src/dashboard/containers/DashboardPage';
import { PivotTableProps } from './types';
import { StyledContainer, usePresetTheme } from '../../common/styles';
import { useTableStateUpdate } from '../../common/utils/useTableStateUpdate';
import {
  defaultColDef,
  defaultColGroupDef,
  useColDefs,
} from './utils/useColDefs';
import { AUTO_SIZE_STRATEGY, PAGE_SIZE_OPTIONS } from './consts';
import { GroupCellRenderer } from './renderers/GroupCellRenderer';
import { getVerboseMetricLabel } from './utils/getVerboseMetricLabel';
import { useGetContextMenuItems } from './utils/useGetContextMenuItems';
import DrillByModal from '../../common/drillBy/DrillByModal';
import { DrillSource } from '../../common/types';

const TableChart = ({
  data,
  groupby,
  metrics,
  verboseMap,
  currencyFormat,
  valueFormat,
  colTotals,
  colSubTotals,
  rowTotals,
  width,
  height,
  metricColorFormatters,
  setControlValue,
  pivotTableState,
  allowRenderHtml,
  dateFormatters,
  selectedFilters,
  setDataMask,
  emitCrossFilters,
  rawFormData,
  expandPivotGroups,
}: PivotTableProps) => {
  const gridRef = useRef<AgGridReact | null>(null);
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

  const tableStateMemoized = useMemo(() => pivotTableState, []);

  const rowData = useMemo(() => data, [data]);
  const colDefs = useColDefs({
    groupby,
    metrics,
    verboseMap,
    metricColorFormatters,
    currencyFormat,
    valueFormat,
    dateFormatters,
    pivotTableState: tableStateMemoized,
  });

  const handleTableStateUpdate = useTableStateUpdate(
    setControlValue,
    [],
    dashboardPageId,
    pivotTableState?.pagination?.pageSize,
    'pivot_table_state',
  );

  const containerStyles = useMemo(() => ({ height, width }), [height, width]);
  const presetTheme = usePresetTheme({ columnBorder: true });

  const toggleFilter = useCallback(
    (e: CellClickedEvent) => {
      const val = e.value;
      const col = e.node.field;
      if (!col || e.node.footer) {
        return;
      }
      const isSelected = selectedFilters?.[col] && selectedFilters[col] === val;

      let filters;
      if (!isSelected) {
        if (val === null || val === undefined) {
          filters = [
            {
              col,
              op: 'IS NULL' as const,
            },
          ];
        } else {
          filters = [
            {
              col,
              op: 'IN' as const,
              val: [val],
            },
          ];
        }
      }
      setDataMask({
        extraFormData: {
          filters,
        },
        filterState: {
          value: !isSelected ? [val] : null,
          selectedFilters: !isSelected ? { [col]: val } : null,
        },
      });
    },
    [setDataMask, selectedFilters],
  );

  const drillByAdditionalConfig = useMemo(
    () =>
      rawFormData.drillByAdditionalConfig || {
        onSelection: setDrillByModalProps,
      },
    [rawFormData.drillByAdditionalConfig],
  );

  const getContextMenuItems = useGetContextMenuItems(
    rawFormData,
    selectedFilters,
    toggleFilter,
    setDrillToDetailFilters,
    drillByAdditionalConfig,
    !!emitCrossFilters,
    !!dashboardPageId,
  );

  const currentAggFunc =
    gridRef.current?.api?.getValueColumns()?.[0]?.getAggFunc() ??
    pivotTableState?.aggregation?.aggregationModel?.[0]?.aggFunc;

  // if there's only one metric, we remove pivot header group with the metric name,
  // so we use it as the auto group column name
  const autoGroupHeaderName = useMemo(
    () =>
      metrics.length === 1
        ? typeof currentAggFunc === 'string'
          ? `${currentAggFunc}(${getVerboseMetricLabel(
              metrics[0],
              verboseMap,
            )})`
          : getVerboseMetricLabel(metrics[0], verboseMap)
        : 'Group',
    [currentAggFunc, metrics, verboseMap],
  );

  const autoGroupColumnDef: ColDef = useMemo(
    () => ({
      headerName: autoGroupHeaderName,
      cellRenderer: 'agGroupCellRenderer',
      cellClass: dashboardPageId && 'non-metric-cell',
      onCellClicked: dashboardPageId ? toggleFilter : undefined,
      cellRendererParams: {
        innerRendererParams: {
          selectedFilters,
          allowRenderHtml,
          sliceId: rawFormData.slice_id,
        },
        innerRenderer: GroupCellRenderer,
        suppressCount: true,
      },
    }),
    [
      allowRenderHtml,
      toggleFilter,
      selectedFilters,
      rawFormData.slice_id,
      dashboardPageId,
      autoGroupHeaderName,
    ],
  );

  const sideBarConfig: SideBarDef | undefined = useMemo(
    () =>
      !dashboardPageId
        ? {
            toolPanels: [
              {
                id: 'columns',
                labelDefault: 'Columns',
                labelKey: 'columns',
                iconKey: 'columns',
                toolPanel: 'agColumnsToolPanel',
                toolPanelParams: {
                  suppressPivotMode: true,
                },
              },
            ],
            defaultToolPanel: 'columns',
            position: 'left',
          }
        : undefined,
    [dashboardPageId],
  );

  const onGridChange = useCallback(
    (e: GridReadyEvent | GridColumnsChangedEvent) => {
      if (!rawFormData.drillByAdditionalConfig) {
        return;
      }
      const { type, currentColumn } = rawFormData.drillByAdditionalConfig;
      if (type === DrillSource.PIVOT) {
        e.api.setPivotColumns([currentColumn]);
      } else {
        e.api.setRowGroupColumns([currentColumn]);
      }
    },
    [rawFormData.drillByAdditionalConfig],
  );

  return (
    <StyledContainer style={containerStyles}>
      <AgGridReact
        ref={gridRef}
        theme={presetTheme}
        defaultColDef={defaultColDef}
        defaultColGroupDef={defaultColGroupDef}
        rowData={rowData}
        columnDefs={colDefs}
        autoSizeStrategy={AUTO_SIZE_STRATEGY}
        pagination
        paginationPageSizeSelector={PAGE_SIZE_OPTIONS}
        pivotColumnGroupTotals={colSubTotals ? 'after' : undefined}
        pivotRowTotals={rowTotals ? 'after' : undefined}
        grandTotalRow={colTotals ? 'bottom' : undefined}
        autoGroupColumnDef={autoGroupColumnDef}
        pivotMode
        pivotPanelShow="always"
        sideBar={sideBarConfig}
        rowGroupPanelShow="always"
        suppressAggFuncInHeader
        suppressDragLeaveHidesColumns
        maintainColumnOrder
        cellSelection
        suppressRowHoverHighlight
        removePivotHeaderRowWhenSingleValueColumn
        onStateUpdated={handleTableStateUpdate}
        initialState={tableStateMemoized}
        getContextMenuItems={getContextMenuItems as GetContextMenuItems}
        pivotDefaultExpanded={expandPivotGroups ? -1 : 0}
        getMainMenuItems={getContextMenuItems as GetMainMenuItems}
        onGridReady={onGridChange}
        onGridColumnsChanged={onGridChange}
      />
      {drillToDetailFilters && (
        <DrillDetailModal
          chartId={rawFormData.slice_id}
          formData={rawFormData}
          initialFilters={drillToDetailFilters}
          showModal={!!drillToDetailFilters}
          onHideModal={() => setDrillToDetailFilters(undefined)}
        />
      )}
      {drillByModalProps && !rawFormData.drillByAdditionalConfig && (
        <DrillByModal
          {...drillByModalProps}
          formData={rawFormData}
          dashboardPageId={dashboardPageId}
          append
        />
      )}
    </StyledContainer>
  );
};

export default TableChart;
