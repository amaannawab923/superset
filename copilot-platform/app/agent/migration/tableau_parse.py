"""Tableau .twb/.twbx parsing primitives (Migration Buddy, A6 tool layer).

Adapted from the tableau-migration/ spike (migrate.py + engine.py), vendored
here as a proper importable module instead of a loose sys.path script. Kept
deliberately narrow for this pass: raw-aggregation measures and plain
group-by dimensions only (no LOD/table-calc SQL resolution — see
MIGRATION_BUDDY_ARCHITECTURE.md's phased roadmap). A worksheet whose calc
formulas need that gets classified NEEDS_REVIEW/UNSUPPORTED and flagged, not
silently mistranslated: keeping measures/dims to what the pandas oracle can
independently recompute is what makes a GREEN verdict actually mean
something (see verify.py).
"""
from __future__ import annotations

import glob
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from typing import Any
from xml.etree.ElementTree import Element

import pandas as pd
import pantab

# Tableau aggregation derivation -> (Superset/SQL aggregate, pandas reducer)
AGG: dict[str, tuple[str, Any]] = {
    "Sum": ("SUM", lambda s: s.sum()),
    "Avg": ("AVG", lambda s: s.mean()),
    "Count": ("COUNT", lambda s: s.count()),
    "CountD": ("COUNT_DISTINCT", lambda s: s.nunique()),
    "Min": ("MIN", lambda s: s.min()),
    "Max": ("MAX", lambda s: s.max()),
}
DATE_DERIVS = {"Year", "Quarter", "Month", "Day", "Week"}
# A calc field whose whole formula is one aggregate wrapped around a bare
# numeric literal (e.g. "MIN(-1.0)", "AVG(0.0)") — Tableau authors commonly
# drop one of these on rows/cols as an invisible spacer to force column
# width/padding in a detail table. It's a real column-instance pill like any
# other, syntactically indistinguishable from a real dimension without
# checking the formula itself — left in, it corrupts GROUP BY (a phantom
# dimension) and describe_workbook's tile summaries alike.
_LITERAL_CALC_RE = re.compile(r"^[A-Z_]+\(\s*-?\d+(?:\.\d+)?\s*\)$")
TABLECALC_RE = re.compile(
    r"WINDOW_|RUNNING_|INDEX\(|RANK\(|LOOKUP\(|TOTAL\(|FIRST\(|LAST\(", re.I
)
LOD_RE = re.compile(r"\{\s*(FIXED|INCLUDE|EXCLUDE)", re.I)


def clean(name: str | None) -> str:
    """``[Order Date]`` -> ``Order Date``."""
    return (name or "").strip("[]")


def load_workbook(twbx_path: str) -> tuple[Element, dict, dict, dict[str, pd.DataFrame]]:
    """Unpack a .twbx and parse it: (twb root, column-instance map, calc
    formulas, {table_name: DataFrame} from the packaged .hyper extract).

    ``frames`` is empty for a live-connection workbook (no packaged extract)
    — callers must handle that (Tier-0 data-oracle verification needs a
    packaged extract; there's no live-source querying in this pass).
    """
    tmp = tempfile.mkdtemp()
    with zipfile.ZipFile(twbx_path) as z:
        z.extractall(tmp)
    twb_path = glob.glob(f"{tmp}/**/*.twb", recursive=True)[0]
    hyper_paths = glob.glob(f"{tmp}/**/*.hyper", recursive=True)
    frames: dict[str, pd.DataFrame] = {}
    if hyper_paths:
        frames = {
            str(k[-1]): v for k, v in pantab.frames_from_hyper(hyper_paths[0]).items()
        }
    root = ET.parse(twb_path).getroot()
    inst = build_instance_map(root)
    formulas = calc_formulas(root)
    return root, inst, formulas, frames


def build_instance_map(root: Element) -> dict[str, tuple[str, str]]:
    """``column-instance`` name (e.g. ``[yr:Order Date:ok]``) -> (base column, derivation)."""
    inst = {}
    for ci in root.iter("column-instance"):
        name = ci.get("name")
        if name:
            inst[name] = (clean(ci.get("column", "")), ci.get("derivation", "None"))
    return inst


def calc_formulas(root: Element) -> dict[str, str]:
    """Calc-field clean name -> Tableau formula string (used to detect LOD/table-calc).

    Only ``class="tableau"`` calcs (the formula-language ones) — bin and
    categorical-bin calcs are a different XML shape entirely (see
    ``synthetic_fields``) and were silently invisible here before, which is
    exactly why they used to slip through classification unflagged."""
    formulas = {}
    for col in root.iter("column"):
        calc = col.find("calculation")
        if calc is not None and calc.get("class") == "tableau":
            formulas[clean(col.get("name", ""))] = calc.get("formula", "") or ""
    return formulas


def _parameter_value(root: Element, param_ref: str) -> float | None:
    """Resolve a ``[Parameters].[Parameter N]`` reference to its current
    numeric value — a parameter's live value lives in the ``value``
    attribute of its own ``<column param-domain-type=...>`` definition."""
    name = clean(param_ref.split(".")[-1]) if "." in param_ref else clean(param_ref)
    for col in root.iter("column"):
        if col.get("param-domain-type") is not None and clean(col.get("name")) == name:
            try:
                return float(col.get("value"))
            except (TypeError, ValueError):
                return None
    return None


def synthetic_fields(root: Element) -> dict[str, dict]:
    """Clean field name -> a resolved spec for Tableau's two *structural*
    (non-formula-language) calculated-field kinds:

    - numeric bin (``class="bin"``): floor a continuous column into fixed-
      width buckets — ``{"kind": "bin", "source_col", "peg", "size"}``.
    - categorical bin / manual group (``class="categorical-bin"``): an
      explicit label -> member-values mapping —
      ``{"kind": "categorical_bin", "source_col", "buckets": [{"label", "values"}]}``.

    These are NOT in ``calc_formulas()`` — different ``class`` value, and
    (for categorical-bin) a different XML shape (child ``<bin>``/``<value>``
    elements, not a ``formula`` attribute) — which is exactly why a bin field
    like "Age (bin)" used to be invisible to classify()'s calc-field check
    and slip through as an ordinary physical column. Both kinds are fully
    deterministic — no formula-language parsing needed — so unlike a
    general ``class="tableau"`` calc, these are resolvable now, not just
    detectable.
    """
    fields: dict[str, dict] = {}
    for col in root.iter("column"):
        calc = col.find("calculation")
        if calc is None:
            continue
        name = clean(col.get("name", ""))
        if not name:
            continue

        if calc.get("class") == "bin":
            source_col = clean(calc.get("formula", ""))
            try:
                peg = float(calc.get("peg", "0") or "0")
            except ValueError:
                peg = 0.0
            size_attr = calc.get("size")
            size = float(size_attr) if size_attr is not None else _parameter_value(
                root, calc.get("size-parameter", "")
            )
            if source_col and size is not None:
                fields[name] = {
                    "kind": "bin", "source_col": source_col, "peg": peg, "size": size,
                }

        elif calc.get("class") == "categorical-bin":
            source_col = clean(calc.get("column", ""))
            buckets = []
            for bin_el in calc.findall("bin"):
                # value="&quot;18-21&quot;" -> the quoted label text
                label = (bin_el.get("value") or "").strip('"')
                # Tableau quotes string member literals ("<value>&quot;Acco&quot;</value>")
                # but not numeric ones ("<value>18</value>") — that quoting
                # presence/absence is itself the type signal, so strip a
                # matched surrounding pair rather than assuming a type.
                values = [
                    v.text[1:-1] if len(v.text) >= 2 and v.text[0] == v.text[-1] == '"' else v.text
                    for v in bin_el.findall("value")
                    if v.text is not None
                ]
                if label and values:
                    buckets.append({"label": label, "values": values})
            if source_col and buckets:
                fields[name] = {
                    "kind": "categorical_bin", "source_col": source_col, "buckets": buckets,
                }

    return fields


def parse_columns(root: Element) -> dict[str, dict[str, str]]:
    """Clean column id -> {caption, role, datatype}, for dimension display labels."""
    cols = {}
    for c in root.iter("column"):
        cid = clean(c.get("name"))
        if not cid:
            continue
        cols[cid] = {
            "caption": c.get("caption") or cid,
            "role": c.get("role", ""),
            "datatype": c.get("datatype", ""),
        }
    return cols


def worksheet_measures(ws: Element, inst: dict) -> list[dict[str, str]]:
    """Raw-aggregation measures actually referenced on this worksheet."""
    seen, measures = set(), []
    for ci in ws.iter("column-instance"):
        deriv = ci.get("derivation")
        if deriv in AGG:
            base = clean(ci.get("column", ""))
            key = (base, deriv)
            if key not in seen:
                seen.add(key)
                measures.append({"col": base, "agg": deriv})
    return measures


def shelf_dims(
    ws: Element, cols: dict[str, dict[str, str]], formulas: dict[str, str]
) -> list[dict[str, str]]:
    """The dimension pills actually on the rows/cols shelves (the true
    group-by) — excludes measure-aggregation pills. Each entry carries the
    date-part derivation (``Year``/``Quarter``/...) when the pill is a date
    truncation, so translate_sql (verify.py) can emit the matching
    EXTRACT/date_trunc instead of grouping by the raw timestamp column.
    """
    inst = {
        ci.get("name"): (clean(ci.get("column")), ci.get("derivation") or "None")
        for ci in ws.iter("column-instance")
    }
    out, seen = [], set()
    for tag in ("rows", "cols"):
        el = ws.find(f".//{tag}")
        if el is None or not el.text:
            continue
        for nm in re.findall(r"(\[[^\]]+\])", el.text):
            if nm not in inst:
                continue
            col, deriv = inst[nm]
            if (
                col
                and not col.startswith(":")
                and deriv not in AGG
                and col not in seen
                and not _LITERAL_CALC_RE.match(formulas.get(col, ""))
            ):
                seen.add(col)
                out.append(
                    {
                        "col": col,
                        "label": cols.get(col, {}).get("caption", col),
                        "deriv": deriv if deriv in DATE_DERIVS else None,
                    }
                )
    return out


def detail_dims(ws: Element, cols: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    """Dimension(s) on the Detail shelf (``<pane><encodings><lod column=...>``)
    — Tableau's per-point identity for a worksheet with no rows/cols
    dimension at all (the scatter-plot shape: two continuous measures on
    rows/cols, the entity that makes each point distinct on Detail).
    ``shelf_dims`` only reads the rows/cols shelf text and is blind to this
    — which is exactly why a 2-measure/0-dim scatter tile used to silently
    collapse to a single-measure big_number: the point-identity dimension
    was never parsed at all.
    """
    out, seen = [], set()
    for enc in ws.iter("lod"):
        colref = enc.get("column", "")
        # An <lod> encoding's column attribute is a direct column-instance
        # reference, e.g. "[federated...].[none:Customer Name:nk]" — pull
        # the last bracketed segment ("none:Customer Name:nk") and split it
        # as deriv:name:role-suffix (the name itself may contain ":", so
        # split from both ends rather than assuming exactly 3 parts).
        m = re.search(r"\[([^\]]+)\]$", colref)
        if not m:
            continue
        parts = m.group(1).split(":")
        if len(parts) < 3:
            continue
        deriv_code = parts[0]
        base = clean(":".join(parts[1:-1]))
        if deriv_code != "none" or not base or base.startswith(":") or base in seen:
            continue
        seen.add(base)
        out.append({"col": base, "label": cols.get(base, {}).get("caption", base), "deriv": None})
    return out


def parse_filters(ws: Element, inst: dict) -> list[dict]:
    """{col, deriv, kind: "in"|"range", members|range} per categorical/quantitative filter."""
    out = []
    for f in ws.iter("filter"):
        cls = f.get("class")
        colref = f.get("column", "")
        m = re.search(r"\[[^\]]*\]\.(\[[^\]]*\])$", colref)
        instname = m.group(1) if m else colref
        base, deriv = inst.get(instname, (clean(instname), "None"))
        if cls == "categorical":
            members = [
                gf.get("member")
                for gf in f.iter("groupfilter")
                if gf.get("function") == "member" and gf.get("member") is not None
            ]
            if members and not base.startswith(":"):
                out.append({"col": base, "deriv": deriv, "kind": "in", "members": members})
        elif cls == "quantitative":
            mn, mx = f.find("min"), f.find("max")
            rng = {
                "min": mn.text if mn is not None else None,
                "max": mx.text if mx is not None else None,
            }
            if base and not base.startswith(":"):
                out.append({"col": base, "deriv": deriv, "kind": "range", "range": rng})
    return out


def apply_filters(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame | None:
    """Return the filtered frame, or None if a filter references a column
    not present in df (the caller must treat that tile as unverifiable)."""
    mask = pd.Series(True, index=df.index)
    for flt in filters:
        col = flt["col"]
        if col not in df.columns:
            return None
        s = df[col]
        if flt["deriv"] == "Year":
            s = pd.to_datetime(s).dt.year.astype(str)
            members = [
                str(int(float(x))) if str(x).replace(".", "").isdigit() else str(x)
                for x in flt["members"]
            ]
        else:
            members = flt["members"] if flt["kind"] == "in" else None
        if flt["kind"] == "in":
            mask &= s.astype(str).isin([str(x) for x in members])
        elif flt["kind"] == "range":
            r = flt["range"]
            if r["min"] is not None:
                mask &= pd.to_numeric(df[col], errors="coerce") >= float(r["min"])
            if r["max"] is not None:
                mask &= pd.to_numeric(df[col], errors="coerce") <= float(r["max"])
    return df[mask]


def where_sql(filters: list[dict]) -> str:
    """Translate extracted filters into a SQL WHERE predicate (no leading ``WHERE``)."""
    parts = []
    for f in filters:
        col = f["col"].replace('"', '""')
        if f["kind"] == "in":
            if f["deriv"] == "Year":
                vals = ",".join(str(int(float(m))) for m in f["members"])
                parts.append(f'EXTRACT(year FROM "{col}") IN ({vals})')
            else:
                vals = ",".join("'" + str(m).replace("'", "''") + "'" for m in f["members"])
                parts.append(f'"{col}" IN ({vals})')
        elif f["kind"] == "range":
            r = f["range"]
            if r.get("min") is not None:
                parts.append(f'"{col}" >= {float(r["min"])}')
            if r.get("max") is not None:
                parts.append(f'"{col}" <= {float(r["max"])}')
    return " AND ".join(parts)


def classify(
    ws: Element,
    measures: list[dict],
    formulas: dict[str, str],
    frames: dict[str, pd.DataFrame],
) -> tuple[str, str]:
    """SIMPLE_AGG (translatable & verifiable) | NEEDS_REVIEW (LOD/table-calc/
    unmatched) | UNSUPPORTED (no Superset equivalent), plus a human reason."""
    marks = [m.get("class") for m in ws.iter("mark")]
    if any(m == "VizExtension" for m in marks):
        return "UNSUPPORTED", "viz extension (no Superset equivalent)"
    for ci in ws.iter("column-instance"):
        base = clean(ci.get("column", ""))
        formula = formulas.get(base, "")
        if TABLECALC_RE.search(formula):
            return "NEEDS_REVIEW", "table calc (not translated in this pass)"
        if LOD_RE.search(formula):
            return "NEEDS_REVIEW", "LOD expression (not translated in this pass)"
    if measures:
        for frame in frames.values():
            if measures[0]["col"] in frame.columns:
                return "SIMPLE_AGG", "aggregation + filters"
        if measures[0]["col"] in formulas:
            # A calc-field measure (e.g. a parameter-driven metric switcher)
            # — distinguish this from "genuinely no measure at all" so the
            # flagged reason names the actual blocker, not a generic one.
            return (
                "NEEDS_REVIEW",
                f'calculated field(s) not translated in this pass: {measures[0]["col"]}',
            )
    return "NEEDS_REVIEW", "no directly translatable aggregate measure"


_AGG_PREFIX = {"sum": "Sum", "avg": "Avg", "cnt": "Count", "cntd": "CountD", "min": "Min", "max": "Max"}


def detail_fields(ws: Element, cols: dict[str, dict[str, str]]) -> list[str]:
    """Every field displayed via a per-pane ``<text>`` encoding — the real
    column list for a Tableau "card"/detail-grid layout (many ``<pane>``
    elements, one field text-encoded per pane — e.g. a scrolling transaction
    list where each row's fields are laid out as separate stacked cards
    rather than a traditional table). ``shelf_dims`` alone is blind to this:
    rows/cols on such a worksheet typically carries just an identity dim
    plus an unrelated multi-measure combo formula, not the real field list —
    each displayed field lives in its own pane's ``<encodings><text>``
    instead, one pane per field.
    """
    out, seen = [], set()
    for enc in ws.iter("encodings"):
        text_el = enc.find("text")
        if text_el is None:
            continue
        colref = text_el.get("column", "")
        m = re.search(r"\[([^\]]+)\]$", colref)
        if not m:
            continue
        parts = m.group(1).split(":")
        if len(parts) < 3:
            continue
        deriv_code, base = parts[0], clean(":".join(parts[1:-1]))
        if not base or base.startswith(":") or base in seen:
            continue
        seen.add(base)
        label = cols.get(base, {}).get("caption", base)
        prefix = _AGG_PREFIX.get(deriv_code)
        out.append(f"{prefix}({label})" if prefix else label)
    return out


def mark_of(ws: Element) -> str:
    marks = [m.get("class") for m in ws.iter("mark")]
    for pref in (
        "VizExtension", "Pie", "Line", "Bar", "GanttBar", "Square",
        "Circle", "Shape", "Area", "Text",
    ):
        if pref in marks:
            return pref
    return marks[0] if marks else "Automatic"


def map_viz(mark: str, n_measures: int, n_dims: int) -> tuple[str, str | None]:
    """Tableau mark type + measure/dim counts -> (Superset viz_type, flag reason|None).

    Mapped to the ChartConfig discriminants generate_chart actually accepts
    (chart_type='xy' with kind='bar'/'line'/'area', 'pie', 'big_number',
    'table' — see apply.py) rather than raw Superset viz_type strings.
    """
    if mark == "VizExtension":
        return "table", "viz-extension -> data table (no Superset equivalent)"
    if mark == "Pie":
        return "pie", None
    if mark == "Line":
        return "line", None
    if mark == "Area":
        return "area", None
    if mark in ("Bar", "GanttBar"):
        return ("bar", None) if n_dims else ("big_number", None)
    if n_measures >= 1 and n_dims == 0:
        return "big_number", None
    if n_measures >= 1 and n_dims >= 1:
        return "bar", None
    return "table", "fallback — no clear measure/dimension shape"


def pick_dashboard(root: Element, want: str | None = None) -> Element | None:
    """The <dashboard> element to migrate: name-substring match if given,
    else the dashboard with the most worksheet-zones (the "overview")."""
    dashboards = list(root.iter("dashboard"))
    if want:
        for d in dashboards:
            if want.lower() in (d.get("name") or "").lower():
                return d
    best, best_n = None, -1
    for d in dashboards:
        n = len([z for z in d.iter("zone") if z.get("name")])
        if n > best_n:
            best, best_n = d, n
    return best


def layout_rows(zones: list[dict]) -> list[list[dict]]:
    """Map Tableau zone x/y/w/h (0-100000 coordinate space) to rows of
    Superset 12-column grid cells (``gw``/``gh`` added to each zone dict)."""
    ordered = sorted(zones, key=lambda z: (int(z["y"]), int(z["x"])))
    rows: list[list[dict]] = []
    current: list[dict] = []
    current_y: int | None = None
    for z in ordered:
        if current_y is None or int(z["y"]) - current_y > 4000:
            if current:
                rows.append(current)
            current, current_y = [z], int(z["y"])
        else:
            current.append(z)
    if current:
        rows.append(current)
    out = []
    for row in rows:
        total_w = sum(int(z["w"]) for z in row) or 1
        out_row = []
        for z in row:
            gw = max(2, min(12, round(int(z["w"]) / total_w * 12)))
            gh = max(20, min(80, round(int(z["h"]) / 100000 * 100)))
            out_row.append({**z, "gw": gw, "gh": gh})
        out.append(out_row)
    return out
