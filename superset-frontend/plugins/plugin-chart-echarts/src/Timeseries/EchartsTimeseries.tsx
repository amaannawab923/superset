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
/* eslint-disable theme-colors/no-literal-colors */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  DTTM_ALIAS,
  BinaryQueryObjectFilterClause,
  AxisType,
  getTimeFormatter,
  getColumnLabel,
  getNumberFormatter,
  LegendState,
  ensureIsArray,
} from '@superset-ui/core';
import type { ViewRootGroup } from 'echarts/types/src/util/types';
import type GlobalModel from 'echarts/types/src/model/Global';
import type ComponentModel from 'echarts/types/src/model/Component';
import { debounce } from 'lodash';
/* eslint-disable import/no-extraneous-dependencies */
import styled from '@emotion/styled';
import { EchartsHandler, EventHandlers } from '../types';
import Echart from '../components/Echart';
import { TimeseriesChartTransformedProps } from './types';
import { formatSeriesName } from '../utils/series';
import { ExtraControls } from '../components/ExtraControls';

const TIMER_DURATION = 300;

// Add these styled components at the top level, outside the component
const TooltipMarker = styled.div`
  position: absolute;
  transform: translate(-50%, -116%);
  background: rgba(0, 0, 0, 0.85);
  padding: 8px 10px;
  border-radius: 4px;
  white-space: pre-wrap;
  pointer-events: auto;
  z-index: 50;
  cursor: pointer;
  user-select: none;
  transition: opacity 0.1s;
  opacity: 0.95;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.25);
  font-size: 12px;
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;

  &::after {
    content: '';
    position: absolute;
    bottom: -6px;
    left: 50%;
    transform: translateX(-50%);
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;

    border-top: 6px solid rgba(0, 0, 0, 0.85);
  }
`;

const TooltipLink = styled.a`
  color: #ffffff;
  text-decoration: none;
  display: block;
  line-height: 1.4;

  &:hover {
    color: #ffffff;
    text-decoration: none;
  }
`;

const TooltipRow = styled.div`
  margin-bottom: 4px;
`;

export default function EchartsTimeseries({
  formData,
  height,
  width,
  echartOptions,
  groupby,
  labelMap,
  selectedValues,
  setDataMask,
  setControlValue,
  legendData = [],
  onContextMenu,
  onLegendStateChanged,
  onFocusedSeries,
  xValueFormatter,
  xAxis,
  refs,
  emitCrossFilters,
  coltypeMapping,
}: TimeseriesChartTransformedProps) {
  const { stack } = formData;
  const echartRef = useRef<EchartsHandler | null>(null);
  // eslint-disable-next-line no-param-reassign
  refs.echartRef = echartRef;
  const clickTimer = useRef<ReturnType<typeof setTimeout>>();
  const extraControlRef = useRef<HTMLDivElement>(null);
  const [extraControlHeight, setExtraControlHeight] = useState(0);
  useEffect(() => {
    const updatedHeight = extraControlRef.current?.offsetHeight || 0;
    setExtraControlHeight(updatedHeight);
  }, [formData.showExtraControls]);

  const hasDimensions = ensureIsArray(groupby).length > 0;
  const insideMarkerRef = useRef(false);
  const cursorPositionRef = useRef({ x: 0, y: 0 });
  const [marker, setMarker] = useState<{
    x: number;
    y: number;
    label: string;
  } | null>(null);

  const getModelInfo = (target: ViewRootGroup, globalModel: GlobalModel) => {
    let el = target;
    let model: ComponentModel | null = null;
    while (el) {
      // eslint-disable-next-line no-underscore-dangle
      const modelInfo = el.__ecComponentInfo;
      if (modelInfo != null) {
        model = globalModel.getComponent(modelInfo.mainType, modelInfo.index);
        break;
      }
      el = el.parent;
    }
    return model;
  };

  const getCrossFilterDataMask = useCallback(
    (value: string) => {
      const selected: string[] = Object.values(selectedValues);
      let values: string[];
      if (selected.includes(value)) {
        values = selected.filter(v => v !== value);
      } else {
        values = [value];
      }
      const groupbyValues = values.map(value => labelMap[value]);
      return {
        dataMask: {
          extraFormData: {
            filters:
              values.length === 0
                ? []
                : groupby.map((col, idx) => {
                    const val = groupbyValues.map(v => v[idx]);
                    if (val === null || val === undefined)
                      return {
                        col,
                        op: 'IS NULL' as const,
                      };
                    return {
                      col,
                      op: 'IN' as const,
                      val: val as (string | number | boolean)[],
                    };
                  }),
          },
          filterState: {
            label: groupbyValues.length ? groupbyValues : undefined,
            value: groupbyValues.length ? groupbyValues : null,
            selectedValues: values.length ? values : null,
          },
        },
        isCurrentValueSelected: selected.includes(value),
      };
    },
    [groupby, labelMap, selectedValues],
  );

  const handleChange = useCallback(
    (value: string) => {
      if (!emitCrossFilters) {
        return;
      }
      setDataMask(getCrossFilterDataMask(value).dataMask);
    },
    [emitCrossFilters, setDataMask, getCrossFilterDataMask],
  );

  // Update isOverDataPoint to consider marker state
  const isOverDataPoint = useCallback((x: number, y: number) => {
    const instance = echartRef.current?.getEchartInstance();
    if (!instance) return false;

    // If we're inside the marker tooltip, consider it as being over a point
    if (insideMarkerRef.current) {
      return true;
    }

    // Find points near mouse position
    const result = instance.containPixel({ seriesIndex: 'all' }, [x, y]);

    return result;
  }, []);

  // Add debounced marker update
  const updateMarker = useCallback(
    debounce((params: any) => {
      const instance = echartRef.current?.getEchartInstance();

      // Get mouse position from event
      const coords = instance?.convertToPixel(
        { seriesIndex: params.seriesIndex },
        params.data.value || params.data,
      ) as unknown as [number, number];
      console.log(params, 'params');

      if (coords && isOverDataPoint(coords[0], coords[1])) {
        setMarker({
          x: coords[0],
          y: coords[1],
          label: params?.data?.label,
        });
      }
    }, 0),
    [isOverDataPoint],
  );

  // Add debounced cursor position checker
  const checkCursorPosition = useCallback(
    debounce(() => {
      if (!marker || insideMarkerRef.current) return;

      const cursorPos = cursorPositionRef.current;

      const distance = Math.sqrt(
        Math.pow(cursorPos.x - marker.x, 2) +
          Math.pow(cursorPos.y - marker.y, 2),
      );

      if (distance > 5) {
        setMarker(null);
      }
    }, 0),
    [marker],
  );

  // Track cursor position
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      const targetClassName =
        // @ts-ignore
        typeof e?.target?.className === 'string'
          ? // @ts-ignore
            e?.target?.className || ''
          : '';
      if (targetClassName.includes('marker')) return;
      const container = echartRef.current?.getEchartInstance()?.getDom();
      if (!container) return;

      const rect = container.getBoundingClientRect();
      cursorPositionRef.current = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      };

      checkCursorPosition();
    };

    document.addEventListener('mousemove', handleMouseMove);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      checkCursorPosition.cancel();
    };
  }, [checkCursorPosition]);

  const eventHandlers: EventHandlers = {
    click: props => {
      if (!hasDimensions) {
        return;
      }
      if (clickTimer.current) {
        clearTimeout(clickTimer.current);
      }
      // Ensure that double-click events do not trigger single click event. So we put it in the timer.
      clickTimer.current = setTimeout(() => {
        const { seriesName: name } = props;
        handleChange(name);
      }, TIMER_DURATION);
    },
    mousemove: params => {
      if (params.componentType === 'series') {
        updateMarker(params);
      }
    },
    mouseout: () => {
      checkCursorPosition();
    },
    legendselectchanged: payload => {
      onLegendStateChanged?.(payload.selected);
    },
    legendselectall: payload => {
      onLegendStateChanged?.(payload.selected);
    },
    legendinverseselect: payload => {
      onLegendStateChanged?.(payload.selected);
    },
    contextmenu: async eventParams => {
      if (onContextMenu) {
        eventParams.event.stop();
        const { data, seriesName } = eventParams;
        const drillToDetailFilters: BinaryQueryObjectFilterClause[] = [];
        const drillByFilters: BinaryQueryObjectFilterClause[] = [];
        const pointerEvent = eventParams.event.event;
        const values = [
          ...(eventParams.name ? [eventParams.name] : []),
          ...(labelMap[seriesName] ?? []),
        ];
        const groupBy = ensureIsArray(formData.groupby);
        if (data && xAxis.type === AxisType.Time) {
          drillToDetailFilters.push({
            col:
              // if the xAxis is '__timestamp', granularity_sqla will be the column of filter
              xAxis.label === DTTM_ALIAS
                ? formData.granularitySqla
                : xAxis.label,
            grain: formData.timeGrainSqla,
            op: '==',
            val: data[0],
            formattedVal: xValueFormatter(data[0]),
          });
        }
        [
          ...(xAxis.type === AxisType.Category && data ? [xAxis.label] : []),
          ...groupBy,
        ].forEach((dimension, i) =>
          drillToDetailFilters.push({
            col: dimension,
            op: '==',
            val: values[i],
            formattedVal: String(values[i]),
          }),
        );
        groupBy.forEach((dimension, i) => {
          const val = labelMap[seriesName][i];
          drillByFilters.push({
            col: dimension,
            op: '==',
            val,
            formattedVal: formatSeriesName(values[i], {
              timeFormatter: getTimeFormatter(formData.dateFormat),
              numberFormatter: getNumberFormatter(formData.numberFormat),
              coltype: coltypeMapping?.[getColumnLabel(dimension)],
            }),
          });
        });

        onContextMenu(pointerEvent.clientX, pointerEvent.clientY, {
          drillToDetail: drillToDetailFilters,
          drillBy: { filters: drillByFilters, groupbyFieldName: 'groupby' },
          crossFilter: hasDimensions
            ? getCrossFilterDataMask(seriesName)
            : undefined,
        });
      }
    },
  };

  const zrEventHandlers: EventHandlers = {
    dblclick: params => {
      // clear single click timer
      if (clickTimer.current) {
        clearTimeout(clickTimer.current);
      }
      const pointInPixel = [params.offsetX, params.offsetY];
      const echartInstance = echartRef.current?.getEchartInstance();
      if (echartInstance?.containPixel('grid', pointInPixel)) {
        // do not trigger if click unstacked chart's blank area
        if (!stack && params.target?.type === 'ec-polygon') return;
        // @ts-ignore
        const globalModel = echartInstance.getModel();
        const model = getModelInfo(params.target, globalModel);
        if (model) {
          const { name } = model;
          const legendState: LegendState = legendData.reduce(
            (previous, datum) => ({
              ...previous,
              [datum]: datum === name,
            }),
            {},
          );
          onLegendStateChanged?.(legendState);
        }
      }
    },
  };

  // Add mousemove tracking at container level
  useEffect(() => {
    const container = echartRef.current?.getEchartInstance()?.getDom();

    const handleMouseLeave = () => {
      setMarker(null);
    };

    if (container) {
      container.addEventListener('mouseleave', handleMouseLeave);
    }

    return () => {
      if (container) {
        container.removeEventListener('mouseleave', handleMouseLeave);
      }
    };
  }, []);

  // Add cleanup for debounced function
  useEffect(
    () => () => {
      updateMarker.cancel();
    },
    [updateMarker],
  );

  return (
    <>
      <div ref={extraControlRef}>
        <ExtraControls formData={formData} setControlValue={setControlValue} />
      </div>
      {marker && (
        <TooltipMarker
          className="marker"
          style={{
            left: marker.x,
            top: marker.y,
          }}
          onMouseEnter={e => {
            e.stopPropagation();
            setTimeout(() => {
              insideMarkerRef.current = true;
            }, 0);
          }}
          onMouseLeave={e => {
            e.stopPropagation();
            setTimeout(() => {
              insideMarkerRef.current = false;
              checkCursorPosition();
            }, 0);
          }}
        >
          <TooltipLink
            href="http://google.com"
            target="_blank"
            rel="noopener noreferrer"
          >
            <TooltipRow>{marker?.label}</TooltipRow>
          </TooltipLink>
        </TooltipMarker>
      )}
      <Echart
        ref={echartRef}
        refs={refs}
        height={height - extraControlHeight}
        width={width}
        echartOptions={echartOptions}
        eventHandlers={eventHandlers}
        zrEventHandlers={zrEventHandlers}
        selectedValues={selectedValues}
      />
    </>
  );
}
