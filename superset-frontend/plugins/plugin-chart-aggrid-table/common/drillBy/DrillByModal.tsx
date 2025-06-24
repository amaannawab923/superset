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

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BaseFormData,
  Column,
  QueryData,
  css,
  ensureIsArray,
  isDefined,
  t,
  useTheme,
  ContextMenuFilters,
} from '@superset-ui/core';
import { useDispatch, useSelector } from 'react-redux';
import { Link } from 'react-router-dom';
import { noop } from 'lodash';
import { Modal, Loading, Button, Alert } from '@superset-ui/core/components';
import { RootState } from 'src/dashboard/types';
import { postFormData } from 'src/explore/exploreUtils/formData';
import { simpleFilterToAdhoc } from 'src/utils/simpleFilterToAdhoc';
import { useDatasetMetadataBar } from 'src/features/datasets/metadataBar/useDatasetMetadataBar';
import { useToasts } from 'src/components/MessageToasts/withToasts';
import { logEvent } from 'src/logger/actions';
import {
  LOG_ACTIONS_DRILL_BY_BREADCRUMB_CLICKED,
  LOG_ACTIONS_DRILL_BY_EDIT_CHART,
  LOG_ACTIONS_DRILL_BY_MODAL_OPENED,
  LOG_ACTIONS_FURTHER_DRILL_BY,
} from 'src/logger/LogUtils';
import { findPermission } from 'src/utils/findPermission';
import { getQuerySettings } from 'src/explore/exploreUtils';
import DrillByChart from 'src/components/Chart/DrillBy/DrillByChart';
import { Dataset, DrillByType } from 'src/components/Chart/types';
import {
  getChartDataRequest,
  handleChartDataResponse,
} from 'src/components/Chart/chartAction';
import { useDisplayModeToggle } from 'src/components/Chart/DrillBy/useDisplayModeToggle';
// import {
//   DrillByBreadcrumb,
//   useDrillByBreadcrumbs,
// } from 'src/components/Chart/DrillBy/useDrillByBreadcrumbs';
import { useResultsTableView } from 'src/components/Chart/DrillBy/useResultsTableView';
import { DrillSource } from '../types';

const DEFAULT_ADHOC_FILTER_FIELD_NAME = 'adhoc_filters';
interface ModalFooterProps {
  closeModal?: () => void;
  formData: BaseFormData;
  dashboardPageId?: string;
}

const ModalFooter = ({
  formData,
  closeModal,
  dashboardPageId,
}: ModalFooterProps) => {
  const dispatch = useDispatch();
  const { addDangerToast } = useToasts();
  const theme = useTheme();
  const [url, setUrl] = useState('');
  const onEditChartClick = useCallback(() => {
    dispatch(
      logEvent(LOG_ACTIONS_DRILL_BY_EDIT_CHART, {
        slice_id: formData.slice_id,
      }),
    );
  }, [dispatch, formData.slice_id]);
  const canExplore = useSelector((state: RootState) =>
    findPermission('can_explore', 'Superset', state.user?.roles),
  );

  const [datasource_id, datasource_type] = formData.datasource.split('__');
  useEffect(() => {
    if (dashboardPageId) {
      postFormData(Number(datasource_id), datasource_type, formData, 0)
        .then(key => {
          setUrl(
            `/explore/?form_data_key=${key}&dashboard_page_id=${dashboardPageId}`,
          );
        })
        .catch(() => {
          addDangerToast(t('Failed to generate chart edit URL'));
        });
    }
  }, [addDangerToast, datasource_id, datasource_type, formData]);
  const isEditDisabled = !url || !canExplore;

  return (
    <>
      <Button
        buttonStyle="secondary"
        buttonSize="small"
        onClick={onEditChartClick}
        disabled={isEditDisabled}
        tooltip={
          isEditDisabled
            ? t('You do not have sufficient permissions to edit the chart')
            : undefined
        }
      >
        <Link
          css={css`
            &:hover {
              text-decoration: none;
            }
          `}
          to={url}
        >
          {t('Edit chart')}
        </Link>
      </Button>

      <Button
        buttonStyle="primary"
        buttonSize="small"
        onClick={closeModal}
        data-test="close-drill-by-modal"
        css={css`
          margin-left: ${theme.sizeUnit * 2}px;
        `}
      >
        {t('Close')}
      </Button>
    </>
  );
};

export interface DrillByModalProps {
  column?: Column;
  dataset: Dataset;
  drillByConfig: Required<ContextMenuFilters>['drillBy'] & {
    currentColumn?: string;
    type?: DrillSource;
  };
  formData: BaseFormData & { [key: string]: any };
  onHideModal: () => void;
  canDownload: boolean;
  dashboardPageId?: string;
  append?: boolean;
}

type DrillByConfigs = (ContextMenuFilters['drillBy'] & {
  column?: Column;
  type?: DrillSource;
})[];

export default function DrillByModal({
  column,
  dataset,
  drillByConfig,
  formData,
  onHideModal,
  canDownload,
  dashboardPageId,
  append,
}: DrillByModalProps) {
  const dispatch = useDispatch();
  const theme = useTheme();
  const { addDangerToast } = useToasts();
  const [isChartDataLoading, setIsChartDataLoading] = useState(true);

  const [drillByConfigs, setDrillByConfigs] = useState<DrillByConfigs>([
    { ...drillByConfig, column },
  ]);

  useEffect(() => {
    dispatch(
      logEvent(LOG_ACTIONS_DRILL_BY_MODAL_OPENED, {
        slice_id: formData.slice_id,
      }),
    );
  }, [dispatch, formData.slice_id]);

  const {
    column: currentColumn,
    groupbyFieldName = drillByConfig.groupbyFieldName,
    type,
  } = drillByConfigs[drillByConfigs.length - 1] || {};

  const initialGroupbyColumns = useMemo(
    () =>
      ensureIsArray(formData[groupbyFieldName])
        .map(colName =>
          dataset.columns?.find(col => col.column_name === colName),
        )
        .filter(isDefined),
    [dataset.columns, formData, groupbyFieldName],
  );

  const { displayModeToggle, drillByDisplayMode } = useDisplayModeToggle();
  const [chartDataResult, setChartDataResult] = useState<QueryData[]>();

  const resultsTable = useResultsTableView(
    chartDataResult,
    formData.datasource,
    canDownload,
  );

  const [currentFormData, setCurrentFormData] = useState(formData);
  const [usedGroupbyColumns, setUsedGroupbyColumns] = useState<Column[]>(
    [...initialGroupbyColumns, column].filter(isDefined),
  );
  const [breadcrumbsData, setBreadcrumbsData] = useState<DrillByBreadcrumb[]>([
    { groupby: initialGroupbyColumns, filters: drillByConfig.filters },
    { groupby: column || [] },
  ]);

  const getNewGroupby = useCallback(
    (groupbyCol: Column, fieldName = groupbyFieldName) =>
      Array.isArray(formData[fieldName])
        ? [groupbyCol.column_name]
        : groupbyCol.column_name,
    [formData, groupbyFieldName],
  );

  const getFormDataChangesFromConfigs = useCallback(
    (configs: DrillByConfigs) =>
      configs.reduce(
        (acc, config) => {
          if (config?.groupbyFieldName && config.column) {
            acc.formData[config.groupbyFieldName] = append
              ? [
                  ...ensureIsArray(acc.formData[config.groupbyFieldName]),
                  ...ensureIsArray(
                    getNewGroupby(config.column, config.groupbyFieldName),
                  ),
                ]
              : getNewGroupby(config.column, config.groupbyFieldName);
            acc.overridenGroupbyFields.add(config.groupbyFieldName);
          }
          const adhocFilterFieldName =
            config?.adhocFilterFieldName || DEFAULT_ADHOC_FILTER_FIELD_NAME;
          acc.formData[adhocFilterFieldName] = [
            ...ensureIsArray(acc[adhocFilterFieldName]),
            ...ensureIsArray(config.filters).map(filter =>
              simpleFilterToAdhoc(filter),
            ),
          ];
          acc.overridenAdhocFilterFields.add(adhocFilterFieldName);

          return acc;
        },
        {
          formData: {},
          overridenGroupbyFields: new Set<string>(),
          overridenAdhocFilterFields: new Set<string>(),
        },
      ),
    [getNewGroupby, append],
  );

  const getFiltersFromConfigsByFieldName = useCallback(
    () =>
      drillByConfigs.reduce((acc, config) => {
        const adhocFilterFieldName =
          config.adhocFilterFieldName || DEFAULT_ADHOC_FILTER_FIELD_NAME;
        acc[adhocFilterFieldName] = [
          ...(acc[adhocFilterFieldName] || []),
          ...config.filters.map(filter => simpleFilterToAdhoc(filter)),
        ];
        return acc;
      }, {}),
    [drillByConfigs],
  );

  const onBreadcrumbClick = useCallback(
    (breadcrumb: DrillByBreadcrumb, index: number) => {
      dispatch(
        logEvent(LOG_ACTIONS_DRILL_BY_BREADCRUMB_CLICKED, {
          slice_id: formData.slice_id,
        }),
      );
      setDrillByConfigs(prevConfigs => prevConfigs.slice(0, index));
      setBreadcrumbsData(prevBreadcrumbs => {
        const newBreadcrumbs = prevBreadcrumbs.slice(0, index + 1);
        delete newBreadcrumbs[newBreadcrumbs.length - 1].filters;
        return newBreadcrumbs;
      });
      setUsedGroupbyColumns(prevUsedGroupbyColumns =>
        prevUsedGroupbyColumns.slice(0, index),
      );
      setCurrentFormData(() => {
        if (index === 0) {
          return formData;
        }
        const { formData: overrideFormData, overridenAdhocFilterFields } =
          getFormDataChangesFromConfigs(drillByConfigs.slice(0, index));

        const newFormData = {
          ...formData,
          ...overrideFormData,
        };
        overridenAdhocFilterFields.forEach(adhocFilterField => ({
          ...newFormData,
          [adhocFilterField]: [
            ...formData[adhocFilterField],
            ...overrideFormData[adhocFilterField],
          ],
        }));
        return newFormData;
      });
    },
    [dispatch, drillByConfigs, formData, getFormDataChangesFromConfigs],
  );

  const breadcrumbs = useDrillByBreadcrumbs(breadcrumbsData, onBreadcrumbClick);

  const drilledFormData = useMemo(() => {
    let updatedFormData = { ...currentFormData };
    if (currentColumn && groupbyFieldName) {
      updatedFormData[groupbyFieldName] = append
        ? Array.from(
            new Set([
              ...ensureIsArray(
                initialGroupbyColumns.map(col => col.column_name),
              ),
              ...ensureIsArray(updatedFormData[groupbyFieldName]),
              ...ensureIsArray(getNewGroupby(currentColumn)),
            ]),
          )
        : getNewGroupby(currentColumn);
    }

    const adhocFilters = getFiltersFromConfigsByFieldName();
    Object.keys(adhocFilters).forEach(adhocFilterFieldName => {
      updatedFormData = {
        ...updatedFormData,
        [adhocFilterFieldName]: [
          ...ensureIsArray(formData[adhocFilterFieldName]),
          ...adhocFilters[adhocFilterFieldName],
        ],
      };
    });

    updatedFormData.slice_id = 0;
    delete updatedFormData.slice_name;
    delete updatedFormData.dashboards;
    return updatedFormData;
  }, [
    currentFormData,
    currentColumn,
    groupbyFieldName,
    getFiltersFromConfigsByFieldName,
    getNewGroupby,
    formData.adhoc_filters,
  ]);

  useEffect(() => {
    setUsedGroupbyColumns(usedCols =>
      !currentColumn ||
      usedCols.some(
        usedCol => usedCol.column_name === currentColumn.column_name,
      )
        ? usedCols
        : [...usedCols, currentColumn],
    );
  }, [currentColumn]);

  const onSelection = useCallback(
    (
      newColumn: Column,
      drillByConfig: Required<ContextMenuFilters>['drillBy'],
    ) => {
      dispatch(
        logEvent(LOG_ACTIONS_FURTHER_DRILL_BY, {
          drill_depth: drillByConfigs.length + 1,
          slice_id: formData.slice_id,
        }),
      );
      setDrillByConfigs(prevConfigs => [
        ...prevConfigs,
        { ...drillByConfig, column: newColumn },
      ]);
      setCurrentFormData(drilledFormData);
      setBreadcrumbsData(prevBreadcrumbs => {
        const newBreadcrumbs = [...prevBreadcrumbs, { groupby: newColumn }];
        newBreadcrumbs[newBreadcrumbs.length - 2].filters =
          drillByConfig.filters;
        return newBreadcrumbs;
      });
    },
    [dispatch, drillByConfigs.length, drilledFormData, formData.slice_id],
  );

  const handleSelection = useCallback(
    ({
      column: newColumn,
      drillByConfig: newDrillByConfig,
    }: {
      column: Column;
      drillByConfig: Required<ContextMenuFilters>['drillBy'];
    }) => {
      onSelection(newColumn, newDrillByConfig);
    },
    [onSelection],
  );

  const chartName = useSelector<RootState, string | undefined>(state => {
    const chartLayoutItem = Object.values(state.dashboardLayout.present).find(
      layoutItem => layoutItem.meta?.chartId === formData.slice_id,
    );
    return (
      chartLayoutItem?.meta.sliceNameOverride || chartLayoutItem?.meta.sliceName
    );
  });

  useEffect(() => {
    if (drilledFormData) {
      const [useLegacyApi] = getQuerySettings(drilledFormData);
      setIsChartDataLoading(true);
      setChartDataResult(undefined);
      getChartDataRequest({
        formData: drilledFormData,
      })
        .then(({ response, json }) =>
          handleChartDataResponse(response, json, useLegacyApi),
        )
        .then(queriesResponse => {
          setChartDataResult(queriesResponse);
        })
        .catch(() => {
          addDangerToast(t('Failed to load chart data.'));
        })
        .finally(() => {
          setIsChartDataLoading(false);
        });
    }
  }, [addDangerToast, drilledFormData]);
  const { metadataBar } = useDatasetMetadataBar({ dataset });

  const drilledFormDataWithAdditionalConfig = useMemo(
    () => ({
      ...drilledFormData,
      drillByAdditionalConfig: {
        excludedColumns: usedGroupbyColumns,
        onSelection: handleSelection,
        currentColumn: currentColumn?.column_name,
        type,
      },
    }),
    [drilledFormData, usedGroupbyColumns],
  );

  return (
    <Modal
      css={css`
        .ant-modal-footer {
          border-top: none;
        }
      `}
      show
      onHide={onHideModal ?? (() => null)}
      title={t('Drill by: %s', chartName)}
      footer={
        <ModalFooter
          formData={drilledFormData}
          dashboardPageId={dashboardPageId}
        />
      }
      responsive
      resizable
      resizableConfig={{
        minHeight: theme.gridUnit * 128,
        minWidth: theme.gridUnit * 128,
        defaultSize: {
          width: 'auto',
          height: '80vh',
        },
      }}
      draggable
      destroyOnClose
      maskClosable={false}
    >
      <div
        css={css`
          display: flex;
          flex-direction: column;
          height: 100%;
        `}
      >
        {metadataBar}
        {breadcrumbs}
        {displayModeToggle}
        {isChartDataLoading && <Loading />}
        {!isChartDataLoading && !chartDataResult && (
          <Alert
            type="error"
            message={t('There was an error loading the chart data')}
          />
        )}
        {drillByDisplayMode === DrillByType.Chart && chartDataResult && (
          <DrillByChart
            dataset={dataset}
            formData={drilledFormDataWithAdditionalConfig}
            result={chartDataResult}
            onContextMenu={noop}
            inContextMenu={false}
          />
        )}
        {drillByDisplayMode === DrillByType.Table &&
          chartDataResult &&
          resultsTable}
      </div>
    </Modal>
  );
}
