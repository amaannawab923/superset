export const dateFilterComparator = {
  comparator: (filterLocalDateAtMidnight: Date, cellValue: Date) => {
    if (cellValue == null) {
      return -1;
    }

    const cellDate = new Date(cellValue);
    cellDate.setHours(0, 0, 0, 0);

    if (filterLocalDateAtMidnight.getTime() === cellDate.getTime()) {
      return 0;
    }
    if (cellDate < filterLocalDateAtMidnight) {
      return -1;
    }
    if (cellDate > filterLocalDateAtMidnight) {
      return 1;
    }
    return 0;
  },
};
