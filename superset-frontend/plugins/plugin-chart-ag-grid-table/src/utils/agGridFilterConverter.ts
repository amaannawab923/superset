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

/**
 * AG Grid Filter Model types
 */
export type AgGridFilterType = 'text' | 'number' | 'date' | 'set' | 'boolean';

export type AgGridFilterOperator =
  | 'equals'
  | 'notEqual'
  | 'contains'
  | 'notContains'
  | 'startsWith'
  | 'endsWith'
  | 'lessThan'
  | 'lessThanOrEqual'
  | 'greaterThan'
  | 'greaterThanOrEqual'
  | 'inRange'
  | 'blank'
  | 'notBlank';

export type AgGridLogicalOperator = 'AND' | 'OR';

export interface AgGridSimpleFilter {
  filterType: AgGridFilterType;
  type: AgGridFilterOperator;
  filter?: any;
  filterTo?: any;
  dateFrom?: string | null;
  dateTo?: string | null;
}

export interface AgGridCompoundFilter {
  filterType: AgGridFilterType;
  operator: AgGridLogicalOperator;
  condition1: AgGridSimpleFilter;
  condition2: AgGridSimpleFilter;
  conditions?: AgGridSimpleFilter[];
}

export interface AgGridSetFilter {
  filterType: 'set';
  values: string[];
}

export type AgGridFilterModel = Record<
  string,
  AgGridSimpleFilter | AgGridCompoundFilter | AgGridSetFilter
>;

/**
 * SQLAlchemy Filter Object (Superset format)
 */
export interface SQLAlchemyFilter {
  col: string;
  op: string;
  val: any;
}

/**
 * Converted Filter Result
 */
export interface ConvertedFilter {
  simpleFilters: SQLAlchemyFilter[];
  complexWhere?: string;
}

/**
 * AG Grid to SQLAlchemy operator mapping
 */
const AG_GRID_TO_SQLA_OPERATOR_MAP: Record<AgGridFilterOperator, string> = {
  equals: '==',
  notEqual: '!=',
  contains: 'ILIKE',
  notContains: 'NOT ILIKE',
  startsWith: 'ILIKE',
  endsWith: 'ILIKE',
  lessThan: '<',
  lessThanOrEqual: '<=',
  greaterThan: '>',
  greaterThanOrEqual: '>=',
  inRange: 'BETWEEN',
  blank: 'IS NULL',
  notBlank: 'IS NOT NULL',
};

/**
 * Format value for SQL based on operator
 */
function formatValueForOperator(
  operator: AgGridFilterOperator,
  value: any,
): any {
  if (operator === 'contains' || operator === 'notContains') {
    return `%${value}%`;
  }
  if (operator === 'startsWith') {
    return `${value}%`;
  }
  if (operator === 'endsWith') {
    return `%${value}`;
  }
  return value;
}

function simpleFilterToWhereClause(
  columnName: string,
  filter: AgGridSimpleFilter,
): string {
  const { type } = filter;
  const value = getFilterValue(filter);
  const filterTo = getFilterToValue(filter);
  const operator = AG_GRID_TO_SQLA_OPERATOR_MAP[type];

  if (type === 'blank') {
    return `${columnName} IS NULL`;
  }

  if (type === 'notBlank') {
    return `${columnName} IS NOT NULL`;
  }

  if (type === 'inRange' && filterTo !== undefined) {
    if (isDateFilter(filter)) {
      return `${columnName} BETWEEN '${value}' AND '${filterTo}'`;
    }
    return `${columnName} BETWEEN ${value} AND ${filterTo}`;
  }

  const formattedValue = formatValueForOperator(type, value);

  if (operator === 'ILIKE' || operator === 'NOT ILIKE') {
    return `${columnName} ${operator} '${formattedValue}'`;
  }

  if (typeof formattedValue === 'string') {
    return `${columnName} ${operator} '${formattedValue}'`;
  }

  return `${columnName} ${operator} ${formattedValue}`;
}

function isCompoundFilter(
  filter: AgGridSimpleFilter | AgGridCompoundFilter | AgGridSetFilter,
): filter is AgGridCompoundFilter {
  return (
    'operator' in filter && ('condition1' in filter || 'conditions' in filter)
  );
}

function isSetFilter(
  filter: AgGridSimpleFilter | AgGridCompoundFilter | AgGridSetFilter,
): filter is AgGridSetFilter {
  return filter.filterType === 'set' && 'values' in filter;
}

function isDateFilter(filter: AgGridSimpleFilter): boolean {
  return filter.filterType === 'date';
}

function getFilterValue(filter: AgGridSimpleFilter): any {
  if (isDateFilter(filter)) {
    return filter.dateFrom;
  }
  return filter.filter;
}

function getFilterToValue(filter: AgGridSimpleFilter): any {
  if (isDateFilter(filter)) {
    return filter.dateTo;
  }
  return filter.filterTo;
}

function convertDateFilterToSQLAlchemy(
  columnName: string,
  filter: AgGridSimpleFilter,
): SQLAlchemyFilter | null {
  const { type } = filter;
  const { dateFrom } = filter;
  const { dateTo } = filter;

  if (type === 'blank') {
    return { col: columnName, op: 'IS NULL', val: null };
  }
  if (type === 'notBlank') {
    return { col: columnName, op: 'IS NOT NULL', val: null };
  }

  if (!dateFrom) {
    return null;
  }

  switch (type) {
    case 'equals':
      return {
        col: columnName,
        op: 'TEMPORAL_RANGE',
        val: `${dateFrom} : ${dateFrom}`,
      };
    case 'notEqual':
      return { col: columnName, op: '!=', val: dateFrom };
    case 'greaterThan':
      return { col: columnName, op: '>', val: dateFrom };
    case 'lessThan':
      return { col: columnName, op: '<', val: dateFrom };
    case 'greaterThanOrEqual':
      return { col: columnName, op: '>=', val: dateFrom };
    case 'lessThanOrEqual':
      return { col: columnName, op: '<=', val: dateFrom };
    case 'inRange':
      if (!dateTo) {
        return null;
      }
      return {
        col: columnName,
        op: 'TEMPORAL_RANGE',
        val: `${dateFrom} : ${dateTo}`,
      };
    default:
      return null;
  }
}

function compoundFilterToWhereClause(
  columnName: string,
  filter: AgGridCompoundFilter,
): string {
  const { operator, condition1, condition2, conditions } = filter;

  if (conditions && conditions.length > 0) {
    const clauses = conditions.map(cond =>
      simpleFilterToWhereClause(columnName, cond),
    );
    return `(${clauses.join(` ${operator} `)})`;
  }

  const clause1 = simpleFilterToWhereClause(columnName, condition1);
  const clause2 = simpleFilterToWhereClause(columnName, condition2);

  return `(${clause1} ${operator} ${clause2})`;
}

export function convertAgGridFiltersToSQL(
  filterModel: AgGridFilterModel,
): ConvertedFilter {
  const simpleFilters: SQLAlchemyFilter[] = [];
  const complexWhereClauses: string[] = [];

  Object.entries(filterModel).forEach(([columnName, filter]) => {
    if (isSetFilter(filter)) {
      simpleFilters.push({
        col: columnName,
        op: 'IN',
        val: filter.values,
      });
      return;
    }

    if (isCompoundFilter(filter)) {
      const whereClause = compoundFilterToWhereClause(columnName, filter);
      complexWhereClauses.push(whereClause);
      return;
    }

    const simpleFilter = filter as AgGridSimpleFilter;
    const { type } = simpleFilter;

    if (isDateFilter(simpleFilter)) {
      const dateFilter = convertDateFilterToSQLAlchemy(
        columnName,
        simpleFilter,
      );
      if (dateFilter) {
        simpleFilters.push(dateFilter);
      }
      return;
    }

    if (type === 'blank') {
      simpleFilters.push({
        col: columnName,
        op: 'IS NULL',
        val: null,
      });
      return;
    }

    if (type === 'notBlank') {
      simpleFilters.push({
        col: columnName,
        op: 'IS NOT NULL',
        val: null,
      });
      return;
    }

    const value = getFilterValue(simpleFilter);
    const operator = AG_GRID_TO_SQLA_OPERATOR_MAP[type];
    const formattedValue = formatValueForOperator(type, value);

    simpleFilters.push({
      col: columnName,
      op: operator,
      val: formattedValue,
    });
  });

  const complexWhere =
    complexWhereClauses.length > 0
      ? `(${complexWhereClauses.join(' AND ')})`
      : undefined;

  return {
    simpleFilters,
    complexWhere,
  };
}
