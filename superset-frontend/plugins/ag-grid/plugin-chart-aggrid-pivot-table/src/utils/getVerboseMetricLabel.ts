import { getMetricLabel, JsonObject, QueryFormMetric } from '@superset-ui/core';

export const getVerboseMetricLabel = (
  metric: QueryFormMetric,
  verboseMap: JsonObject,
) => {
  const label = getMetricLabel(metric);
  return verboseMap[label] || label;
};
