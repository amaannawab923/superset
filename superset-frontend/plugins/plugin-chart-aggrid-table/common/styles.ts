import { css, styled, useTheme } from '@superset-ui/core';
import { useMemo } from 'react';
import { themeQuartz } from 'ag-grid-community';

export const usePresetTheme = (
  themeOverrides: Parameters<(typeof themeQuartz)['withParams']>[0] = {},
) => {
  const theme = useTheme();
  return useMemo(
    () =>
      themeQuartz.withParams({
        accentColor: theme.colors.primary.base,
        borderRadius: '2px',
        browserColorScheme: 'light',
        fontFamily: 'inherit',
        headerFontSize: theme.fontSizeSM,
        fontSize: theme.fontSizeSM,
        spacing: '6px',
        wrapperBorderRadius: '2px',
        iconSize: theme.fontSizeSM,
        rowGroupIndentSize: theme.sizeUnit * 3,
        ...themeOverrides,
      }),
    [theme],
  );
};

export const StyledContainer = styled.div`
  ${({ theme }) => css`
    --ag-line-height: 18px;
    text-align: left;
    & .non-metric-cell {
      cursor: pointer;
      &:hover {
        background-color: ${theme.colors.grayscale.light4};
      }
      &:has(.active-filter-cell) {
        background-color: ${theme.colors.grayscale.light3};
      }
    }
    & .ag-cell {
      display: flex;
      height: unset;
      min-height: 100%;
    }
    & .ag-cell-wrapper {
      flex: 1;
    }
    & .ag-column-drop-cell-button {
      display: none;
    }
    .ag-popup {
      z-index: 1000;
    }
    & .ag-row-footer {
      background-color: var(--ag-header-background-color);
    }

    &
      .ag-sort-indicator-icon.ag-sort-order
      ~ .ag-sort-indicator-icon.ag-sort-descending-icon,
    &
      .ag-sort-indicator-icon.ag-sort-order
      ~ .ag-sort-indicator-icon.ag-sort-ascending-icon {
      padding-left: 0;
    }

    &
      .ag-ltr
      .ag-header-cell:not(.ag-right-aligned-header)
      .ag-header-menu-icon {
      margin-left: ${theme.sizeUnit}px;
    }
  `}
`;
