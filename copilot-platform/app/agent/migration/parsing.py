"""ChartPlan extraction — the workbook-to-tile-list step (A6 tool layer).

Turns a .twbx into a list of ChartPlans, one per worksheet the target
dashboard actually places (not every worksheet in the workbook — a `.twb`
commonly has far more worksheets than are ever placed on a dashboard).
This is the fix for tile-as-worksheet never being tied to a real dashboard:
`tableau_parse.pick_dashboard` + `layout_rows` give each tile its real
position, and `layout_rows`' row/column grouping gives the fan-out in
verify.py a stable, deterministic processing order.
"""
from __future__ import annotations

from typing import TypedDict
from xml.etree.ElementTree import Element

import pandas as pd

from . import tableau_parse as tp


class ChartPlan(TypedDict):
    sheet: str
    viz_type: str
    measures: list[dict]  # [{"col": str, "agg": "Sum"|"Avg"|"Count"|"CountD"|"Min"|"Max"}]
    # [{"col", "label", "deriv", "synthetic": {...} | None}] — "synthetic" is
    # set when the dim is a Tableau bin/categorical-bin (see tableau_parse.
    # synthetic_fields); verify.py's translate_sql/data_oracle branch on it.
    dims: list[dict]
    filters: list[dict]
    gw: int  # Superset grid width, 2-12
    gh: int  # relative row height, 20-80
    row_y: int  # Tableau y-coordinate, for stable ordering within a row
    row_index: int  # which visual row (from layout_rows) this tile belongs to
    klass: str  # "SIMPLE_AGG" | "NEEDS_REVIEW" | "UNSUPPORTED"
    reason: str


def load_workbook(
    twbx_path: str,
) -> tuple[Element, dict, dict, dict[str, pd.DataFrame], pd.DataFrame | None]:
    """(root, inst, formulas, frames, primary).

    ``primary`` is the packaged-extract table with the most columns (same
    heuristic the tested tile_graph.py prototype uses), or None when the
    workbook has no packaged extract — Tier-0 data-oracle verification is
    unavailable for those; callers should flag every tile RED rather than
    attempt translation with nothing to verify against.
    """
    root, inst, formulas, frames = tp.load_workbook(twbx_path)
    primary = max(frames.values(), key=lambda d: d.shape[1]) if frames else None
    return root, inst, formulas, frames, primary


class TileSummary(TypedDict):
    name: str
    type: str
    measures: list[str]
    dims: list[str]
    uses_calc: bool


class TabSummary(TypedDict):
    name: str
    tiles: list[TileSummary]


def _friendly_tile_type(mark: str, n_measures: int, n_dims: int, measure_labels: list[str]) -> str:
    """Best-effort human label for a tile's chart type, from its Tableau
    mark class and shelf shape. Not exhaustive — Tableau's mark metadata
    doesn't distinguish a lat/long map from an unrelated two-measure KPI,
    so this leans on the common convention (bare Avg(Latitude)/
    Avg(Longitude) measures, no dims) rather than a definitive signal."""
    lower_labels = {m.split("(", 1)[-1].rstrip(")").lower() for m in measure_labels}
    if mark in ("Shape", "Text") and n_measures == 0 and n_dims == 0:
        return "decoration"
    if mark == "Automatic" and n_measures == 0 and n_dims == 0:
        return "text/label"
    if {"latitude", "longitude"} <= lower_labels:
        return "map"
    if mark == "Pie":
        return "pie chart"
    if mark == "Line":
        return "line chart"
    if mark == "Area":
        return "area chart"
    if mark in ("Bar", "GanttBar"):
        return "bar chart" if n_dims else "big number"
    if mark in ("Circle", "Square") and n_dims >= 3:
        return "detail grid"
    if n_measures >= 1 and n_dims == 0:
        return "big number"
    if n_measures >= 1 and n_dims >= 1:
        return "bar/table"
    if n_dims >= 1:
        return "table"
    return f"other (mark={mark})"


def describe_workbook(root: Element, inst: dict, formulas: dict) -> list[TabSummary]:
    """Every dashboard/tab in the workbook, and every tile placed on each —
    name, best-effort chart type, and human-readable measure/dim labels.
    Pure reconnaissance: no verification, no data touched, no MCP calls —
    safe to run on any workbook (even one with no packaged extract) as the
    first thing Migration Buddy reports back, before anyone decides whether
    to actually migrate anything."""
    cols = tp.parse_columns(root)
    ws_by_name = {w.get("name"): w for w in root.iter("worksheet") if w.get("name")}

    def label(colname: str) -> str:
        return cols.get(colname, {}).get("caption", colname)

    # <dashboard> elements appear in the .twb in *definition* order, which
    # doesn't match the tab bar's *display* order — <windows><window> lists
    # every window (dashboards AND individual worksheet preview windows,
    # interleaved) in the order Tableau Desktop actually shows them. Sort
    # dashboards by their position there so tab numbering matches what a
    # user clicking through the published viz actually sees.
    window_order = [w.get("name") for w in root.iter("window")]
    dashboards = sorted(
        root.iter("dashboard"),
        key=lambda d: window_order.index(d.get("name"))
        if d.get("name") in window_order
        else len(window_order),
    )

    tabs: list[TabSummary] = []
    for d in dashboards:
        name = d.get("name") or "Dashboard"
        zones_el = d.find("zones") or d
        seen: set[str] = set()
        tiles: list[TileSummary] = []
        for z in zones_el.iter("zone"):
            wsname = z.get("name")
            if not wsname or not z.get("x") or wsname in seen:
                continue
            seen.add(wsname)
            ws = ws_by_name.get(wsname)
            if ws is None:
                continue
            mark = tp.mark_of(ws)
            measures = tp.worksheet_measures(ws, inst)
            dims = tp.shelf_dims(ws, cols, formulas)
            mlabels = [f'{m["agg"]}({label(m["col"])})' for m in measures]
            dlabels = [label(d["col"]) for d in dims]
            uses_calc = any(m["col"] in formulas for m in measures) or any(
                d["col"] in formulas for d in dims
            )
            if mark in ("Circle", "Square"):
                # A Tableau "card" layout (a scrolling list where each
                # displayed field is its own pane, not a rows/cols shelf
                # pill — see tp.detail_fields) reports a truer field list
                # than rows/cols scanning, which only sees an identity dim
                # plus an unrelated multi-measure combo formula on such a
                # worksheet. Prefer it whenever it actually finds more.
                card_fields = tp.detail_fields(ws, cols)
                if len(card_fields) > len(mlabels) + len(dlabels):
                    mlabels, dlabels = [], card_fields
            tiles.append(
                TileSummary(
                    name=wsname,
                    type=_friendly_tile_type(mark, len(measures), len(dims), mlabels),
                    measures=mlabels,
                    dims=dlabels,
                    uses_calc=uses_calc,
                )
            )
        tabs.append(TabSummary(name=name, tiles=tiles))
    return tabs


def pick_target_dashboard(root: Element, want: str | None = None) -> Element | None:
    """The <dashboard> to migrate — by name-substring if given, else the
    dashboard with the most worksheet-zones (the de facto "overview")."""
    return tp.pick_dashboard(root, want)


def plan_tiles(
    root: Element,
    dashboard: Element,
    inst: dict,
    formulas: dict,
    frames: dict[str, pd.DataFrame],
) -> list[ChartPlan]:
    """One ChartPlan per worksheet zoned onto ``dashboard``, in the
    dashboard's own row/column layout order."""
    cols = tp.parse_columns(root)
    synthetic = tp.synthetic_fields(root)
    physical_cols = {c for frame in frames.values() for c in frame.columns}
    ws_by_name = {w.get("name"): w for w in root.iter("worksheet") if w.get("name")}

    # <dashboard> commonly has sibling <zones> (the default/desktop layout)
    # and <devicelayouts><devicelayout name="Phone">... another full copy of
    # the same zones ...</devicelayout></devicelayouts>. dashboard.iter("zone")
    # walks both — scope to the primary layout only, or every zone (and
    # every tile) is duplicated once per device layout.
    primary_zones_el = dashboard.find("zones") or dashboard
    zones = [
        {
            "ws": z.get("name"),
            "x": z.get("x"),
            "y": z.get("y"),
            "w": z.get("w"),
            "h": z.get("h"),
        }
        for z in primary_zones_el.iter("zone")
        if z.get("name") and z.get("x")
    ]

    tiles: list[ChartPlan] = []
    seen_sheets: set[str] = set()
    for row_index, row in enumerate(tp.layout_rows(zones)):
        for z in row:
            # Some dashboards place the same worksheet in more than one zone
            # (e.g. a small persistent view repeated elsewhere on the
            # canvas). Migrate each worksheet to exactly one chart — keep
            # the first (topmost/leftmost, per layout_rows' ordering).
            if z["ws"] in seen_sheets:
                continue
            ws = ws_by_name.get(z["ws"])
            if ws is None:
                continue  # a zone referencing something other than a worksheet (e.g. a text/legend zone)
            seen_sheets.add(z["ws"])

            measures = tp.worksheet_measures(ws, inst)
            dims = tp.shelf_dims(ws, cols, formulas)
            filters = tp.parse_filters(ws, inst)

            # A worksheet with 2+ continuous measures and no rows/cols
            # dimension is Tableau's scatter-plot shape — the per-point
            # identity dimension lives on the Detail shelf, not rows/cols,
            # and shelf_dims() alone can't see it. Without this, a scatter
            # tile silently collapsed to a single-measure big_number (a
            # real bug: one whole measure just disappears).
            is_scatter = False
            if len(measures) >= 2 and not dims:
                detail = tp.detail_dims(ws, cols)
                if detail:
                    dims = detail[:1]  # one identity dim keeps group_by simple
                    is_scatter = True

            # Attach the resolved bin/categorical-bin spec to any dim built
            # from one — enables translate_sql/data_oracle (verify.py) to
            # build real FLOOR/CASE SQL instead of a raw (nonexistent)
            # column reference. Only when the underlying source column is
            # itself real data — a bin over a calc field is out of scope.
            for d in dims:
                spec = synthetic.get(d["col"])
                if spec and spec["source_col"] in physical_cols:
                    d["synthetic"] = spec
                else:
                    d["synthetic"] = None

            klass, reason = tp.classify(ws, measures, formulas, frames)

            # classify() only checks the *first* measure against physical
            # columns and never looks at dims at all — a calc-based dim
            # (e.g. a grouping IF/CASE calc, not itself LOD/table-calc so it
            # doesn't match classify()'s regexes) would otherwise slip
            # through as SIMPLE_AGG while referencing a "column" that's
            # actually a formula, not real data in `primary`. Every
            # measure/dim col must be a real calc-free field OR a resolved
            # synthetic (bin/categorical-bin) field — those ARE translatable,
            # unlike a general formula calc, so they don't count here.
            if klass == "SIMPLE_AGG":
                calc_cols = (
                    [m["col"] for m in measures if m["col"] in formulas]
                    + [d["col"] for d in dims if d["col"] in formulas and not d["synthetic"]]
                    # A filter on a calc field (e.g. a parameter-driven date-
                    # range boolean) can't be applied by the data-oracle
                    # (tp.apply_filters returns None for a non-physical
                    # column) or by the real chart SQL (the column doesn't
                    # exist in the deployed dataset) — catch it here rather
                    # than let the tile reach SIMPLE_AGG, waste a verify+
                    # build cycle, and fail with a confusing "verified but
                    # could not build" message.
                    + [f["col"] for f in filters if f["col"] in formulas]
                )
                if calc_cols:
                    klass = "NEEDS_REVIEW"
                    reason = f"calculated field(s) not translated in this pass: {', '.join(calc_cols)}"
                elif any(d["col"] in synthetic and not d["synthetic"] for d in dims):
                    # A bin/group field whose SOURCE column isn't real data
                    # (e.g. binned off another calc) — distinct, more
                    # specific reason than the generic calc-field message.
                    bad = [d["col"] for d in dims if d["col"] in synthetic and not d["synthetic"]]
                    klass = "NEEDS_REVIEW"
                    reason = f"binned/grouped field(s) over non-physical data: {', '.join(bad)}"

            if is_scatter and klass == "SIMPLE_AGG":
                # Superset's echarts_timeseries_scatter treats x_axis as a
                # raw grouping column, not an aggregated metric — the
                # aggregate on a ColumnRef assigned to 'x' is silently
                # dropped (superset/mcp_service/chart/chart_utils.py's
                # map_xy_config uses config.x.name only). It can't
                # faithfully render two independently-aggregated continuous
                # measures the way Tableau's scatter does, so the built
                # chart would silently diverge from what was verified.
                # table shows the same dims+aggregated-measures the oracle
                # checked — verified data the user can actually trust.
                viz_type, viz_flag = "table", None
            else:
                viz_type, viz_flag = tp.map_viz(tp.mark_of(ws), len(measures), len(dims))
            if viz_flag and klass == "SIMPLE_AGG":
                # Measures/filters are translatable and verifiable, but the
                # mark type doesn't map to a clean chart shape — still worth
                # shipping as a verified table rather than dropping the tile.
                viz_type, reason = "table", viz_flag

            tiles.append(
                ChartPlan(
                    sheet=z["ws"],
                    viz_type=viz_type,
                    measures=measures,
                    dims=dims,
                    filters=filters,
                    gw=z["gw"],
                    gh=z["gh"],
                    row_y=int(z["y"]),
                    row_index=row_index,
                    klass=klass,
                    reason=reason,
                )
            )
    return tiles
