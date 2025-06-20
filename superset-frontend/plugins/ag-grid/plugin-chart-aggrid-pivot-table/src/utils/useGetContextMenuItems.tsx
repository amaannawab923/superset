import {
  CellClickedEvent,
  DefaultMenuItem,
  GetContextMenuItems,
  GetContextMenuItemsParams,
  GetMainMenuItems,
  GetMainMenuItemsParams,
  IMenuActionParams,
  MenuItemDef,
} from 'ag-grid-community';
import { useCallback, useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import rison from 'rison';
import { last, zip } from 'lodash';
import {
  t,
  FeatureFlag,
  isFeatureEnabled,
  BinaryQueryObjectFilterClause,
  ensureIsArray,
  logging,
  Column,
  DataRecordFilters,
  DataRecordValue,
} from '@superset-ui/core';
import { Dataset } from 'src/components/Chart/types';
import { RootState } from 'src/dashboard/types';
import {
  supersetGetCache,
  cachedSupersetGet,
} from 'src/utils/cachedSupersetGet';
import { useToasts } from 'src/components/MessageToasts/withToasts';
import { useVerboseMap as getVerboseMap } from 'src/hooks/apiResources/datasets';
import { usePermissions } from 'src/hooks/usePermissions';
import { DrillByConfig, PivotTableQueryFormData } from '../types';
import { DrillSource } from '../../../common/types';

export const getDrillToDetailFilters = (drillToDetailItems: any[]) => {
  const drillToDetailFilters: BinaryQueryObjectFilterClause[] = [];
  drillToDetailItems.forEach(([key, val]) => {
    drillToDetailFilters.push({
      col: key,
      op: '==',
      val: val || null,
    });
  });
  return drillToDetailFilters;
};

const queryString = rison.encode({
  columns: [
    'table_name',
    'owners.first_name',
    'owners.last_name',
    'created_by.first_name',
    'created_by.last_name',
    'created_on_humanized',
    'changed_by.first_name',
    'changed_by.last_name',
    'changed_on_humanized',
    'columns.column_name',
    'columns.verbose_name',
    'columns.groupby',
  ],
});

const isContextMenuParams = (
  params: GetContextMenuItemsParams | GetMainMenuItemsParams,
): params is GetContextMenuItemsParams => params.hasOwnProperty('node');

const isActiveFilterValue = (
  filters: DataRecordFilters | undefined,
  key: string | undefined | null,
  val: DataRecordValue,
) => !!filters && key && filters[key]?.includes(val);

const getRowsMenuItemsCallback = (
  params: GetContextMenuItemsParams,
  filters: DataRecordFilters | undefined,
  datasetColumns: Column[],
  dataset: Dataset | undefined,
  toggleFilter: (event: IMenuActionParams) => void,
  emitCrossFilters: boolean,
  showDrillToDetail: boolean,
  showCrossFilters: boolean,
  showDrillBy: boolean,
  canDownload: boolean,
  setDrillToDetailFilters: (filters: BinaryQueryObjectFilterClause[]) => void,
  drillByConfig: DrillByConfig,
  isDashboard: boolean,
) => {
  const menuItems: (DefaultMenuItem | MenuItemDef)[] = [];
  const isDisabled =
    params.column?.getColId() !== 'ag-Grid-AutoColumn' || params.node?.footer;
  if (isDashboard) {
    const clickedColumnId = params.node?.field;
    const clickedValue = params.value;
    if (showCrossFilters) {
      menuItems.push({
        name: isActiveFilterValue(filters, clickedColumnId, clickedValue)
          ? t('Remove cross-filter')
          : t('Add cross-filter'),
        action: params => toggleFilter(params),
        disabled: isDisabled || !emitCrossFilters,
        tooltip: isDisabled
          ? t("You can't apply cross-filter on this data point.")
          : undefined,
      });
    }
    if (showDrillToDetail) {
      const pivotColumns = params.api
        .getPivotColumns()
        .map(col => col.getColId());
      const pivotKeys = params.column?.getColDef()?.pivotKeys;
      const drillToDetailItems: [
        string | undefined,
        string | undefined | null,
      ][] = [];
      if (clickedColumnId) {
        drillToDetailItems.push([clickedColumnId, clickedValue]);
      }
      if (pivotColumns && pivotKeys) {
        drillToDetailItems.push(...zip(pivotColumns, pivotKeys));
      }
      menuItems.push(
        'separator',
        {
          name: t('Drill to detail'),
          action: () => setDrillToDetailFilters([]),
        },
        {
          name: t('Drill to detail by'),
          subMenu: [
            ...drillToDetailItems
              .filter(([key]) => Boolean(key))
              .map(([key, val]) => ({
                name: val || 'null',
                action: () =>
                  setDrillToDetailFilters([
                    {
                      col: key as string,
                      op: '==',
                      // @ts-ignore
                      val: val || null,
                    },
                  ]),
              })),
            {
              name: t('All'),
              action: () =>
                setDrillToDetailFilters(
                  getDrillToDetailFilters(drillToDetailItems),
                ),
            },
          ],
        },
      );
    }
    if (showDrillBy && clickedColumnId) {
      menuItems.push({
        name: t('Drill by'),
        disabled: isDisabled,
        tooltip: isDisabled
          ? t('Drill by is not available for this data point')
          : undefined,
        subMenu: [
          ...datasetColumns.map(col => ({
            name: col.verbose_name || col.column_name,
            action: () =>
              drillByConfig.onSelection({
                onHideModal: () => drillByConfig.onSelection(null),
                column: col,
                dataset: dataset!,
                canDownload,
                drillByConfig: {
                  groupbyFieldName: 'groupby',
                  currentColumn: col.column_name,
                  type: DrillSource.ROW,
                  filters: [
                    {
                      col: clickedColumnId,
                      op: '==',
                      val: clickedValue,
                    },
                  ],
                },
              }),
          })),
        ],
      });
    }
    menuItems.push('separator');
  }
  menuItems.push('copy', 'copyWithHeaders', 'separator', 'export');
  return menuItems;
};

const getColumnsMenuItemsCallback = (
  params: GetMainMenuItemsParams,
  filters: DataRecordFilters | undefined,
  datasetColumns: Column[],
  dataset: Dataset | undefined,
  toggleFilter: (event: IMenuActionParams) => void,
  emitCrossFilters: boolean,
  showDrillToDetail: boolean,
  showCrossFilters: boolean,
  showDrillBy: boolean,
  canDownload: boolean,
  setDrillToDetailFilters: (filters: BinaryQueryObjectFilterClause[]) => void,
  drillByConfig: DrillByConfig,
  isDashboard: boolean,
) => {
  const menuItems: (DefaultMenuItem | MenuItemDef)[] = [];
  const isDisabled =
    !params.column?.getColDef().pivotKeys?.length &&
    !params.columnGroup?.getColGroupDef()?.pivotKeys?.length;
  if (isDashboard && params.column?.getColId() !== 'ag-Grid-AutoColumn') {
    const pivotColumns = params.api
      .getPivotColumns()
      .map(col => col.getColId());
    let clickedColumnId: string | undefined;
    let clickedValue: string | undefined;
    if (params.column) {
      clickedColumnId = last(pivotColumns);
      clickedValue = params.column.getColDef()?.headerName;
    } else if (params.columnGroup) {
      const pivotKeys = params.columnGroup.getColGroupDef()?.pivotKeys;
      clickedColumnId =
        pivotKeys && pivotKeys.length > 0
          ? pivotColumns[pivotKeys.length - 1]
          : undefined;
      clickedValue = params.columnGroup.getColGroupDef()?.headerName;
    }
    if (showCrossFilters && clickedColumnId && clickedValue) {
      menuItems.push({
        name: isActiveFilterValue(filters, clickedColumnId, clickedValue)
          ? t('Remove cross-filter')
          : t('Add cross-filter'),
        action: () =>
          toggleFilter({
            node: { field: clickedColumnId },
            value: clickedValue,
          } as CellClickedEvent),
        disabled: isDisabled || !emitCrossFilters,
        tooltip: isDisabled
          ? t("You can't apply cross-filter on this data point.")
          : undefined,
      });
    }
    if (showDrillToDetail) {
      const pivotKeys = params.column?.getColDef()?.pivotKeys;
      const drillToDetailItems: [
        string | undefined,
        string | undefined | null,
      ][] = [];
      if (pivotColumns && pivotKeys) {
        drillToDetailItems.push(...zip(pivotColumns, pivotKeys));
      }
      menuItems.push(
        'separator',
        {
          name: t('Drill to detail'),
          action: () => setDrillToDetailFilters([]),
        },
        {
          name: t('Drill to detail by'),
          subMenu: [
            ...drillToDetailItems
              .filter(([key]) => Boolean(key))
              .map(([key, val]) => ({
                name: val || 'null',
                action: () =>
                  setDrillToDetailFilters([
                    {
                      col: key as string,
                      op: '==',
                      // @ts-ignore
                      val: val || null,
                    },
                  ]),
              })),
            {
              name: t('All'),
              action: () =>
                setDrillToDetailFilters(
                  getDrillToDetailFilters(drillToDetailItems),
                ),
            },
          ],
        },
      );
    }
    if (showDrillBy && clickedColumnId && clickedValue) {
      menuItems.push({
        name: t('Drill by'),
        disabled: isDisabled,
        tooltip: isDisabled
          ? t('Drill by is not available for this data point')
          : undefined,
        subMenu: [
          ...datasetColumns.map(col => ({
            name: col.verbose_name || col.column_name,
            action: () =>
              drillByConfig.onSelection({
                onHideModal: () => drillByConfig.onSelection(null),
                column: col,
                dataset: dataset!,
                canDownload,
                drillByConfig: {
                  groupbyFieldName: 'groupby',
                  currentColumn: col.column_name,
                  type: DrillSource.PIVOT,
                  filters: [
                    {
                      col: clickedColumnId!,
                      op: '==',
                      val: clickedValue!,
                    },
                  ],
                },
              }),
          })),
        ],
      });
    }
    menuItems.push('separator');
  }
  menuItems.push(...params.defaultItems, 'separator', 'export');
  return menuItems;
};

export const useGetContextMenuItems: (
  formData: PivotTableQueryFormData,
  filters: DataRecordFilters | undefined,
  toggleFilter: (event: IMenuActionParams) => void,
  setDrillToDetailFilters: (filters: BinaryQueryObjectFilterClause[]) => void,
  drillByConfig: DrillByConfig,
  emitCrossFilters: boolean,
  isDashboard: boolean,
) => GetContextMenuItems | GetMainMenuItems = (
  formData,
  filters,
  toggleFilter,
  setDrillToDetailFilters,
  drillByConfig,
  emitCrossFilters,
  isDashboard,
) => {
  const { addDangerToast } = useToasts();
  const [_, setIsLoadingColumns] = useState(false);
  const [datasetColumns, setDatasetColumns] = useState<Column[]>([]);
  const [dataset, setDataset] = useState<Dataset>();

  const crossFiltersEnabled = useSelector(
    ({ dashboardInfo }: RootState) => dashboardInfo.crossFiltersEnabled,
  );

  const { canDownload, canDrillBy, canDrillToDetail } = usePermissions();

  const isInDrillByModal = formData.drillByAdditionalConfig;

  const showDrillToDetail =
    isFeatureEnabled(FeatureFlag.DrillToDetail) &&
    canDrillToDetail &&
    !isInDrillByModal;
  const showDrillBy = isFeatureEnabled(FeatureFlag.DrillBy) && canDrillBy;
  const showCrossFilters = crossFiltersEnabled && !isInDrillByModal;

  useEffect(() => {
    async function loadOptions() {
      const datasetId = Number(formData.datasource.split('__')[0]);
      try {
        setIsLoadingColumns(true);
        const response = await cachedSupersetGet({
          endpoint: `/api/v1/dataset/${datasetId}?q=${queryString}`,
        });
        const { json } = response;
        const { result } = json;
        const verboseMap = getVerboseMap(result);
        setDataset({ ...result, verbose_map: verboseMap });
        setDatasetColumns(
          ensureIsArray(result.columns)
            .filter(column => column.groupby)
            .filter(
              column =>
                !ensureIsArray(formData.groupby).includes(column.column_name) &&
                ensureIsArray(drillByConfig?.excludedColumns)?.every(
                  excludedCol => excludedCol.column_name !== column.column_name,
                ),
            ),
        );
      } catch (error) {
        logging.error(error);
        supersetGetCache.delete(`/api/v1/dataset/${datasetId}`);
        addDangerToast(t('Failed to load dimensions for drill by'));
      } finally {
        setIsLoadingColumns(false);
      }
    }
    if (showDrillBy) {
      loadOptions();
    }
  }, [formData.datasource, formData.groupby, formData.x_axis, showDrillBy]);

  const rowsContextMenuCallback = useCallback(
    (params: GetContextMenuItemsParams) =>
      getRowsMenuItemsCallback(
        params,
        filters,
        datasetColumns,
        dataset,
        toggleFilter,
        emitCrossFilters ?? false,
        showDrillToDetail,
        showCrossFilters,
        showDrillBy,
        canDownload,
        setDrillToDetailFilters,
        drillByConfig,
        isDashboard,
      ),
    [
      filters,
      dataset,
      datasetColumns,
      toggleFilter,
      emitCrossFilters,
      canDownload,
      setDrillToDetailFilters,
      drillByConfig,
      isDashboard,
    ],
  );

  const columnsContextMenuCallback = useCallback(
    (params: GetMainMenuItemsParams) =>
      getColumnsMenuItemsCallback(
        params,
        filters,
        datasetColumns,
        dataset,
        toggleFilter,
        emitCrossFilters ?? false,
        showDrillToDetail,
        showCrossFilters,
        showDrillBy,
        canDownload,
        setDrillToDetailFilters,
        drillByConfig,
        isDashboard,
      ),
    [
      filters,
      dataset,
      datasetColumns,
      toggleFilter,
      emitCrossFilters,
      canDownload,
      setDrillToDetailFilters,
      drillByConfig,
      isDashboard,
    ],
  );

  return useCallback(
    (params: GetContextMenuItemsParams | GetMainMenuItemsParams) => {
      if (isContextMenuParams(params)) {
        return rowsContextMenuCallback(params);
      }
      return columnsContextMenuCallback(params);
    },
    [columnsContextMenuCallback, rowsContextMenuCallback],
  );
};
