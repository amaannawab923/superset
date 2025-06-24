import {
  Behavior,
  ChartLabel,
  ChartMetadata,
  ChartPlugin,
  t,
} from '@superset-ui/core';
import transformProps from './transformProps';
import thumbnail from './images/thumbnail.png';
import controlPanel from './controlPanel';
import buildQuery from './buildQuery';
import { TableChartFormData, TableChartProps } from './types';

const metadata = new ChartMetadata({
  behaviors: [
    Behavior.InteractiveChart,
    Behavior.DrillToDetail,
    Behavior.DrillBy,
  ],
  suppressContextMenu: true,
  category: t('Table'),
  canBeAnnotationTypes: ['EVENT', 'INTERVAL'],
  label: ChartLabel.Featured,
  description: t(
    'A raw records or aggregate table view of a dataset. The table allows for interactions such as column resizing, reordering, filtering, and more within the table itself.',
  ),
  name: t('Interactive Table'),
  tags: [
    t('Additive'),
    t('Business'),
    t('Pattern'),
    t('Featured'),
    t('Report'),
    t('Sequential'),
    t('Tabular'),
  ],
  thumbnail,
});

export default class AgGridTableChartPlugin extends ChartPlugin<
  TableChartFormData,
  TableChartProps
> {
  constructor() {
    super({
      loadChart: () => import('./TableChart'),
      metadata,
      transformProps,
      controlPanel,
      buildQuery,
    });
  }
}
