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
import { useCallback, useMemo, useState } from 'react';
import {
  AdhocColumn,
  tn,
  QueryFormColumn,
  t,
  isAdhocColumn,
  DynamicGroupByColumn,
} from '@superset-ui/core';
import { ColumnMeta, isColumnMeta } from '@superset-ui/chart-controls';
import { isEmpty } from 'lodash';
import DndSelectLabel from 'src/explore/components/controls/DndColumnSelectControl/DndSelectLabel';
import OptionWrapper from 'src/explore/components/controls/DndColumnSelectControl/OptionWrapper';
import { OptionSelector } from 'src/explore/components/controls/DndColumnSelectControl/utils';
import { DatasourcePanelDndItem } from 'src/explore/components/DatasourcePanel/types';
import { DndItemType } from 'src/explore/components/DndItemType';
import ColumnSelectPopoverTrigger from './ColumnSelectPopoverTrigger';
import { DndControlProps } from './types';

export type DndColumnSelectProps = DndControlProps<QueryFormColumn> & {
  options: ColumnMeta[];
  isTemporal?: boolean;
  disabledTabs?: Set<string>;
};

// Add helper function to detect DynamicGroupByColumn
const isDynamicGroupByColumn = (value: any): value is DynamicGroupByColumn => {
  return (
    typeof value === 'object' &&
    value !== null &&
    'column_name' in value &&
    'default' in value
  );
};

function DndColumnSelect(props: DndColumnSelectProps) {
  const {
    value,
    options,
    multi = true,
    onChange,
    canDelete = true,
    ghostButtonText,
    name,
    label,
    isTemporal,
    disabledTabs,
  } = props;

  const [newColumnPopoverVisible, setNewColumnPopoverVisible] = useState(false);

  const defaultOptionForDynamicGroupBy = useMemo(() => {
    if (props?.name !== 'dynamic_groupby') return null;
    // @ts-ignore
    return props?.form_data?.groupby?.[0] || null;
    // @ts-ignore
  }, [props?.form_data]);

  if (props?.name === 'dynamic_groupby') {
  }

  const optionSelector = useMemo(() => {
    const optionsMap = Object.fromEntries(
      options.map(option => [option.column_name, option]),
    );

    console.log(optionsMap, multi, value, 'optionsMap');

    // Special handling for dynamic_groupby
    if (name === 'dynamic_groupby') {
      // @ts-ignore
      const defaultGroupBy = props?.form_data?.groupby?.[0];

      if (defaultGroupBy) {
        // Create DynamicGroupByColumn from the default groupby
        const dynamicGroupByColumn: DynamicGroupByColumn = {
          column_name: defaultGroupBy,
          default: true,
        };
        type NewValue = QueryFormColumn | DynamicGroupByColumn;

        // Create a new value array with DynamicGroupByColumn at index 0
        let newValue: NewValue[] = [];

        if (value) {
          // Convert value to array if it's not already
          const valueArray = Array.isArray(value) ? value : [value];

          // Filter out the default groupby if it's already in the values
          const filteredValues = valueArray.filter(v => {
            if (typeof v === 'string') {
              return v !== defaultGroupBy;
            }
            if (isDynamicGroupByColumn(v)) {
              return v.column_name !== defaultGroupBy;
            }
            return true;
          });

          // Place DynamicGroupByColumn at index 0, rest after it
          newValue = [dynamicGroupByColumn, ...filteredValues];
        } else {
          // If no value, just use the DynamicGroupByColumn
          newValue = [dynamicGroupByColumn];
        }
        // @ts-ignore
        return new OptionSelector(optionsMap, multi, newValue);
      }
    }

    // Default behavior for non-dynamic_groupby cases
    return new OptionSelector(optionsMap, multi, value);
  }, [multi, options, value, name, props?.form_data]);

  const onDrop = useCallback(
    (item: DatasourcePanelDndItem) => {
      const column = item.value as ColumnMeta;
      if (!optionSelector.multi && !isEmpty(optionSelector.values)) {
        optionSelector.replace(0, column.column_name);
      } else {
        optionSelector.add(column.column_name);
      }
      onChange(optionSelector.getValues());
    },
    [onChange, optionSelector],
  );

  const canDrop = useCallback(
    (item: DatasourcePanelDndItem) => {
      const columnName = (item.value as ColumnMeta).column_name;
      return (
        columnName in optionSelector.options && !optionSelector.has(columnName)
      );
    },
    [optionSelector],
  );

  const onClickClose = useCallback(
    (index: number) => {
      const success = optionSelector.del(index);
      if (success) {
        onChange(optionSelector.getValues());
      }
    },
    [onChange, optionSelector],
  );

  const onShiftOptions = useCallback(
    (dragIndex: number, hoverIndex: number) => {
      const success = optionSelector.swap(dragIndex, hoverIndex);
      if (success) {
        onChange(optionSelector.getValues());
      }
    },
    [onChange, optionSelector],
  );

  const valuesRenderer = useCallback(
    () =>
      optionSelector.values.map((column, idx) => {
        const datasourceWarningMessage =
          isAdhocColumn(column) && column.datasourceWarning
            ? t('This column might be incompatible with current dataset')
            : undefined;

        // Check if column has error_text property (ColumnMeta) or is DynamicGroupByColumn
        const withCaret =
          isAdhocColumn(column) ||
          (isColumnMeta(column) && !column.error_text) ||
          (isDynamicGroupByColumn(column) && !column.default);

        // Check if this is a protected DynamicGroupByColumn
        const isProtectedColumn =
          isDynamicGroupByColumn(column) && column.default === true;

        // If it's a protected column, render without the popover trigger
        if (isProtectedColumn) {
          return (
            <OptionWrapper
              key={idx}
              index={idx}
              clickClose={onClickClose}
              onShiftOptions={onShiftOptions}
              type={`${DndItemType.ColumnOption}_${name}_${label}`}
              canDelete={canDelete && optionSelector.canDelete(idx)}
              column={column}
              datasourceWarningMessage={datasourceWarningMessage}
              withCaret={false}
            />
          );
        }

        // For non-protected columns, render with popover trigger
        return (
          <ColumnSelectPopoverTrigger
            key={idx}
            columns={options}
            onColumnEdit={newColumn => {
              const success = optionSelector.replace(idx, newColumn);
              if (success) {
                onChange(optionSelector.getValues());
              }
            }}
            editedColumn={column}
            isTemporal={isTemporal}
            disabledTabs={disabledTabs}
            disabled={isProtectedColumn}
          >
            <OptionWrapper
              key={idx}
              index={idx}
              clickClose={onClickClose}
              onShiftOptions={onShiftOptions}
              type={`${DndItemType.ColumnOption}_${name}_${label}`}
              canDelete={canDelete && optionSelector.canDelete(idx)}
              column={column}
              datasourceWarningMessage={datasourceWarningMessage}
              withCaret={withCaret}
            />
          </ColumnSelectPopoverTrigger>
        );
      }),
    [
      canDelete,
      isTemporal,
      label,
      name,
      onChange,
      onClickClose,
      onShiftOptions,
      optionSelector,
      options,
    ],
  );

  const addNewColumnWithPopover = useCallback(
    (newColumn: ColumnMeta | AdhocColumn) => {
      if (isColumnMeta(newColumn)) {
        optionSelector.add(newColumn.column_name);
      } else {
        optionSelector.add(newColumn as AdhocColumn);
      }
      onChange(optionSelector.getValues());
    },
    [onChange, optionSelector],
  );

  const togglePopover = useCallback((visible: boolean) => {
    setNewColumnPopoverVisible(visible);
  }, []);

  const closePopover = useCallback(() => {
    togglePopover(false);
  }, [togglePopover]);

  const openPopover = useCallback(() => {
    togglePopover(true);
  }, [togglePopover]);

  const labelGhostButtonText = useMemo(
    () =>
      ghostButtonText ??
      tn(
        'Drop a column here or click',
        'Drop columns here or click',
        multi ? 2 : 1,
      ),
    [ghostButtonText, multi],
  );

  return (
    <div>
      <DndSelectLabel
        onDrop={onDrop}
        canDrop={canDrop}
        valuesRenderer={valuesRenderer}
        accept={DndItemType.Column}
        displayGhostButton={multi || optionSelector.values.length === 0}
        ghostButtonText={labelGhostButtonText}
        onClickGhostButton={openPopover}
        {...props}
      />
      <ColumnSelectPopoverTrigger
        columns={options}
        onColumnEdit={addNewColumnWithPopover}
        isControlledComponent
        togglePopover={togglePopover}
        closePopover={closePopover}
        visible={newColumnPopoverVisible}
        isTemporal={isTemporal}
        disabledTabs={disabledTabs}
      >
        <div />
      </ColumnSelectPopoverTrigger>
    </div>
  );
}

export { DndColumnSelect };
