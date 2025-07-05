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

// Action type constant
export const DUMMY_ACTION = 'dynamicFunctionalities/DUMMY_ACTION';

// Action interface
export interface DummyAction {
  type: typeof DUMMY_ACTION;
}

export const SET_GROUP_BY = 'SET_GROUP_BY';
export interface SetGroupBy {
  type: typeof SET_GROUP_BY;
  groupBy: string;
  chartId: number;
}

export function setGroupBy(groupBy: string, chartId: number): SetGroupBy {
  return {
    type: SET_GROUP_BY,
    groupBy,
    chartId,
  };
}

// Action creator function
export function fireDummyAction(): DummyAction {
  return {
    type: DUMMY_ACTION,
  };
}

// Union type for all actions in this module
export type AnyDynamicFunctionalitiesAction = DummyAction | SetGroupBy;
