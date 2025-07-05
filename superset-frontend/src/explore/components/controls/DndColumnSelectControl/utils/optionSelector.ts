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
import { ColumnMeta, isColumnMeta } from '@superset-ui/chart-controls';
import {
  AdhocColumn,
  ensureIsArray,
  QueryFormColumn,
  isPhysicalColumn,
  t,
  DynamicGroupByColumn,
} from '@superset-ui/core';

// Add helper function to detect DynamicGroupByColumn
export const isDynamicGroupByColumn = (
  value: any,
): value is DynamicGroupByColumn => {
  return (
    typeof value === 'object' &&
    value !== null &&
    'column_name' in value &&
    'default' in value
  );
};

// Add helper function to check if a column is protected (default DynamicGroupByColumn)
export const isProtectedColumn = (
  column: ColumnMeta | AdhocColumn | DynamicGroupByColumn,
): boolean => {
  return isDynamicGroupByColumn(column) && column.default === true;
};

const getColumnNameOrAdhocColumn = (
  column: ColumnMeta | AdhocColumn | DynamicGroupByColumn,
): QueryFormColumn => {
  if (isColumnMeta(column)) {
    return column.column_name;
  }
  if (isDynamicGroupByColumn(column)) {
    return column.column_name;
  }
  return column as AdhocColumn;
};

export class OptionSelector {
  values: (ColumnMeta | AdhocColumn | DynamicGroupByColumn)[];

  options: Record<string, ColumnMeta>;

  multi: boolean;

  constructor(
    options: Record<string, ColumnMeta>,
    multi: boolean,
    initialValues?: QueryFormColumn[] | QueryFormColumn | null,
  ) {
    this.options = options;
    this.multi = multi;
    this.values = ensureIsArray(initialValues)
      .map(value => {
        if (value && isPhysicalColumn(value) && value in options) {
          return options[value];
        }
        if (!isPhysicalColumn(value)) {
          // Check if it's a DynamicGroupByColumn
          if (isDynamicGroupByColumn(value)) {
            return value as DynamicGroupByColumn;
          }
          return value as AdhocColumn;
        }
        return {
          type_generic: 'UNKNOWN',
          column_name: value,
          error_text: t(
            'This column might be incompatible with current dataset',
          ),
        };
      })
      .filter(Boolean) as (ColumnMeta | AdhocColumn | DynamicGroupByColumn)[];
  }

  add(value: QueryFormColumn) {
    if (isPhysicalColumn(value) && value in this.options) {
      this.values.push(this.options[value]);
    } else if (!isPhysicalColumn(value)) {
      // Check if it's a DynamicGroupByColumn
      if (isDynamicGroupByColumn(value)) {
        this.values.push(value as DynamicGroupByColumn);
      } else {
        this.values.push(value as AdhocColumn);
      }
    }
  }

  del(idx: number): boolean {
    // Check if the column is protected (default DynamicGroupByColumn)
    if (isProtectedColumn(this.values[idx])) {
      return false; // Cannot delete protected column
    }
    this.values.splice(idx, 1);
    return true;
  }

  replace(idx: number, value: QueryFormColumn): boolean {
    // Check if the column is protected (default DynamicGroupByColumn)
    if (isProtectedColumn(this.values[idx])) {
      return false; // Cannot replace protected column
    }

    if (this.values[idx]) {
      if (isPhysicalColumn(value)) {
        this.values[idx] = this.options[value];
      } else if (isDynamicGroupByColumn(value)) {
        this.values[idx] = value as DynamicGroupByColumn;
      } else {
        this.values[idx] = value as AdhocColumn;
      }
      return true;
    }
    return false;
  }

  swap(a: number, b: number): boolean {
    // Check if either column is protected (default DynamicGroupByColumn)
    if (
      isProtectedColumn(this.values[a]) ||
      isProtectedColumn(this.values[b])
    ) {
      return false; // Cannot swap protected columns
    }

    [this.values[a], this.values[b]] = [this.values[b], this.values[a]];
    return true;
  }

  has(value: QueryFormColumn): boolean {
    return this.values.some(col => {
      if (isPhysicalColumn(value)) {
        return (
          (col as ColumnMeta).column_name === value ||
          (col as AdhocColumn).label === value ||
          (col as DynamicGroupByColumn).column_name === value
        );
      }
      if (isDynamicGroupByColumn(value)) {
        return (
          (col as ColumnMeta).column_name === value.column_name ||
          (col as AdhocColumn).label === value.column_name ||
          (col as DynamicGroupByColumn).column_name === value.column_name
        );
      }
      return (
        (col as ColumnMeta).column_name === value.label ||
        (col as AdhocColumn).label === value.label ||
        (col as DynamicGroupByColumn).column_name === value.label
      );
    });
  }

  // Add method to check if a column can be deleted
  canDelete(idx: number): boolean {
    return !isProtectedColumn(this.values[idx]);
  }

  // Add method to check if a column can be replaced
  canReplace(idx: number): boolean {
    return !isProtectedColumn(this.values[idx]);
  }

  // Add method to check if columns can be swapped
  canSwap(a: number, b: number): boolean {
    return (
      !isProtectedColumn(this.values[a]) && !isProtectedColumn(this.values[b])
    );
  }

  getValues(): QueryFormColumn[] | QueryFormColumn | undefined {
    if (!this.multi) {
      return this.values.length > 0
        ? getColumnNameOrAdhocColumn(this.values[0])
        : undefined;
    }
    return this.values.map(getColumnNameOrAdhocColumn);
  }
}
