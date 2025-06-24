import {
  BinaryQueryObjectFilterClause,
  Column,
  DataRecordFilters,
  DataRecordValue,
  ensureIsArray,
  FeatureFlag,
  isFeatureEnabled,
  logging,
  t,
} from '@superset-ui/core';
import {
  DefaultMenuItem,
  GetContextMenuItems,
  IMenuActionParams,
  MenuItemDef,
} from 'ag-grid-community';
import { useCallback, useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import rison from 'rison';
import { Dataset } from 'src/components/Chart/types';
import { useToasts } from 'src/components/MessageToasts/withToasts';
import { RootState } from 'src/dashboard/types';
import { useVerboseMap as getVerboseMap } from 'src/hooks/apiResources/datasets';
import { usePermissions } from 'src/hooks/usePermissions';
import {
  cachedSupersetGet,
  supersetGetCache,
} from 'src/utils/cachedSupersetGet';
import { TableDataColumnMeta, TableChartFormData } from '../types';
import { formatColumnValue } from './formatValue';

export const getDrillToDetailFilters = (
  columns: TableDataColumnMeta[],
  params: IMenuActionParams,
) => {
  const drillToDetailFilters: BinaryQueryObjectFilterClause[] = [];
  columns.forEach(col => {
    if (!col.isMetric && !col.isPercentMetric) {
      const val = params.node?.data[col.key];
      const formattedVal = formatColumnValue(col, val)[1];
      drillToDetailFilters.push({
        col: col.key,
        op: '==',
        val,
        formattedVal,
      });
    }
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

export const useGetContextMenuItems: (
  formData: TableChartFormData,
  columns: TableDataColumnMeta[],
  filters: DataRecordFilters | undefined,
  toggleFilter: (event: IMenuActionParams) => void,
  setDrillToDetailFilters: (filters: BinaryQueryObjectFilterClause[]) => void,
  drillByConfig: {
    onSelection: (
      props: {
        column: Column;
        dataset: Dataset;
        canDownload: boolean;
        onHideModal: () => void;
        drillByConfig: {
          filters: BinaryQueryObjectFilterClause[];
          groupbyFieldName: string;
          adhocFilterFieldName?: string;
        };
      } | null,
    ) => void;
    excludedColumns?: Column[];
  },
  emitCrossFilters?: boolean,
  isRawRecords?: boolean,
  dashboardPageId?: string,
) => GetContextMenuItems = (
  formData,
  columns,
  filters,
  toggleFilter,
  setDrillToDetailFilters,
  drillByConfig,
  emitCrossFilters,
  isRawRecords,
  dashboardPageId,
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

  const isActiveFilterValue = useCallback(
    (key: string | undefined, val: DataRecordValue) =>
      !!filters && key && filters[key]?.includes(val),
    [filters],
  );

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
                !ensureIsArray(
                  formData[isRawRecords ? 'all_columns' : 'groupby'],
                ).includes(column.column_name) &&
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

  return useCallback(
    params => {
      const menuItems: (DefaultMenuItem | MenuItemDef)[] = [];
      const isDisabled = (params: IMenuActionParams) =>
        params.column?.getColDef().context?.isMetric ||
        params.column?.getColDef().context?.isPercentMetric;

      if (dashboardPageId) {
        if (showCrossFilters) {
          menuItems.push({
            name: isActiveFilterValue(params.column?.getColId(), params.value)
              ? t('Remove cross-filter')
              : t('Add cross-filter'),
            action: params => toggleFilter(params),
            disabled: isDisabled(params) || !emitCrossFilters,
            tooltip:
              isDisabled(params) &&
              t("You can't apply cross-filter on this data point."),
          });
        }
        if (showDrillToDetail) {
          menuItems.push(
            'separator',
            {
              name: t('Drill to detail'),
              action: () => setDrillToDetailFilters([]),
            },
            {
              name: t('Drill to detail by'),
              subMenu: [
                ...columns
                  .filter(
                    col =>
                      !col.isMetric && !col.isNumeric && !col.isPercentMetric,
                  )
                  .map(col => {
                    const val = params.node?.data[col.key];
                    const formattedVal = formatColumnValue(col, val)[1];
                    return {
                      name: formattedVal,
                      action: () =>
                        setDrillToDetailFilters([
                          {
                            col: col.key,
                            op: '==',
                            val,
                            formattedVal,
                          },
                        ]),
                    };
                  }),
                {
                  name: t('All'),
                  action: params =>
                    setDrillToDetailFilters(
                      getDrillToDetailFilters(columns, params),
                    ),
                },
              ],
            },
          );
        }
        if (showDrillBy) {
          menuItems.push({
            name: t('Drill by'),
            disabled: isDisabled(params),
            tooltip:
              isDisabled(params) &&
              t('Drill by is not available for this data point'),
            subMenu: [
              ...datasetColumns.map(col => ({
                name: col.verbose_name || col.column_name,
                action: (params: IMenuActionParams) =>
                  drillByConfig.onSelection({
                    onHideModal: () => drillByConfig.onSelection(null),
                    column: col,
                    dataset: dataset!,
                    canDownload,
                    drillByConfig: {
                      groupbyFieldName: isRawRecords
                        ? 'all_columns'
                        : 'groupby',
                      filters: [
                        {
                          col: params.column!.getColId(),
                          op: '==',
                          val: params.value,
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
    },
    [
      datasetColumns,
      toggleFilter,
      filters,
      formData.drillByAdditionalConfig,
      isRawRecords,
    ],
  );
};
