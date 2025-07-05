import { AnyDynamicFunctionalitiesAction, SET_GROUP_BY } from './actions';

// Dummy action type
const DUMMY_ACTION = 'dynamicFunctionalities/DUMMY_ACTION';

// Initial state (can be anything, here just an empty object)
const initialState = {
  groupBy: {},
};

export default function dynamicFunctionalities(
  state = initialState,
  action: AnyDynamicFunctionalitiesAction,
) {
  switch (action.type) {
    case DUMMY_ACTION:
      console.log('action fired');
      return state;
    case SET_GROUP_BY:
      return {
        ...state,
        groupBy: {
          ...state.groupBy,
          [action.chartId]: action.groupBy,
        },
      };
    default:
      return state;
  }
}
