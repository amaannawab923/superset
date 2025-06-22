/* eslint-disable camelcase */
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
import { DataRecord } from '@superset-ui/core';

// Basically Col Defs of the Preset Table
export interface InputColumn {
  key: string;
  label: string;
  dataType: number;
  isNumeric: boolean;
  isMetric: boolean;
  isPercentMetric: boolean;
  config: Record<string, any>;
  formatter?: Function;
  originalLabel?: string;
  metricName?: string;
}

interface InputData {
  [key: string]: any;
}

function renameMainKeys(data: Record<string, any>[]): Record<string, any>[] {
  return data.map(row => {
    const newRow: Record<string, any> = {};
    for (const key in row) {
      if (key.startsWith('Main ')) {
        const newKey = key.replace('Main ', '');
        newRow[newKey] = row[key];
      } else {
        newRow[key] = row[key];
      }
    }
    return newRow;
  });
}

function cleanTotals(totals: DataRecord) {
  const cleaned: DataRecord = {};

  for (const [key, value] of Object.entries(totals)) {
    if (key.includes('index')) {
      continue;
    }
    if (key.includes('Main')) {
      const newKey = key.replace('Main ', '');
      cleaned[newKey] = value;
    } else {
      cleaned[key] = value;
    }
  }

  return cleaned;
}

export const useTransformData = (
  data: InputData[],
  totals: DataRecord | undefined,
) => {
  const cleanedTotals = cleanTotals(totals || {});

  return {
    rowData: renameMainKeys(data),
    cleanedTotals,
  };
};
