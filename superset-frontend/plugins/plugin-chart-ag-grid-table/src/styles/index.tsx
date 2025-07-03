import { styled } from '@superset-ui/core';

/* Components for AgGridTable */
// Header Styles
export const Container = styled.div`
  ${({ theme }) => `
    display: flex;
    width: 100%;

    .three-dots-menu {
      align-self: center;
      margin-left: ${theme.sizeUnit}px;
      cursor: pointer;
      padding: ${theme.sizeUnit / 2}px;
      border-radius: ${theme.borderRadius}px;
    }
  `}
`;

export const HeaderContainer = styled.div`
  ${({ theme }) => `
    width: 100%;
    display: flex;
    align-items: center;
    cursor: pointer;
    padding: 0 ${theme.sizeUnit * 2}px;
    overflow: hidden;
  `}
`;

export const HeaderLabel = styled.span`
  ${({ theme }) => `
    font-weight: ${theme.fontWeightStrong};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: block;
    max-width: 100%;
  `}
`;

export const SortIconWrapper = styled.div`
  ${({ theme }) => `
    display: flex;
    align-items: center;
    margin-left: ${theme.sizeUnit * 2}px;
  `}
`;

export const FilterIconWrapper = styled.div`
  align-self: flex-end;
  margin-left: auto;
  cursor: pointer;
`;

export const MenuContainer = styled.div`
  ${({ theme }) => `
    min-width: ${theme.sizeUnit * 45}px;
    padding: ${theme.sizeUnit}px 0;

    .menu-item {
      padding: ${theme.sizeUnit * 2}px ${theme.sizeUnit * 4}px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: ${theme.sizeUnit * 2}px;

      &:hover {
        background-color: ${theme.colors.primary.light4};
      }
    }

    .menu-divider {
      height: 1px;
      background-color: ${theme.colors.grayscale.light2};
      margin: ${theme.sizeUnit}px 0;
    }
  `}
`;

export const PopoverWrapper = styled.div`
  position: relative;
  display: inline-block;
`;

export const PopoverContainer = styled.div`
  ${({ theme }) => `
    position: fixed;
    background: ${theme.colors.grayscale.light4};
    border: 1px solid ${theme.colors.grayscale.light2};
    border-radius: ${theme.borderRadius}px;
    box-shadow: 0 ${theme.sizeUnit / 2}px ${theme.sizeUnit * 2}px ${theme.colors.grayscale.light1}40;
    z-index: 99;
    min-width: ${theme.sizeUnit * 50}px;
    padding: ${theme.sizeUnit * 2}px;
  `}
`;
