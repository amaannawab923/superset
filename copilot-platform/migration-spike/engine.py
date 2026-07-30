#!/usr/bin/env python3
"""engine.py — ONE generic Tableau .twbx -> Superset dashboard compiler.

No per-workbook code. Everything is read from the .twb at runtime:
  * calc formulas are resolved to SQL (arithmetic, IF->CASE, date fns, aggregates)
  * each worksheet's mark type -> a Superset viz_type; its measures/dims/filters
    -> chart params
  * the dashboard's <zone> x/y/w/h -> the Superset grid layout

Emits a workbook-agnostic "IR" JSON that the generic builder (build_ir.py)
turns into datasets + charts + a dashboard.  A sheet the resolver can't handle
is FLAGGED (rendered as a data table), never silently dropped.

Usage: engine.py /path/to/workbook.twbx  [dashboard-name-substring]
"""
import sys, os, re, json, glob, zipfile, tempfile, hashlib
import xml.etree.ElementTree as ET
import migrate  # reuse load_hyper, parse_filters, where_sql, build_instance_map, calc_formulas, AGG

AGG_FN = {"Sum": "SUM", "Avg": "AVG", "Count": "COUNT", "CountD": "COUNT_DISTINCT",
          "Min": "MIN", "Max": "MAX"}
# constructs the v1 resolver does not translate -> flag the calc (degrade to table)
HARD = re.compile(
    r"\{\s*(FIXED|INCLUDE|EXCLUDE)|WINDOW_|RUNNING_|LOOKUP\(|INDEX\(|RANK\(|TOTAL\("
    r"|FIRST\(|LAST\(|MAKEPOINT|MAKELINE|SPLIT\(|DATENAME\(|DATEDIFF\(|DATEADD\(|\bINT\(", re.I)


def _split_args(argstr):
    args, depth, cur = [], 0, ""
    for ch in argstr:
        if ch == "(":
            depth += 1; cur += ch
        elif ch == ")":
            depth -= 1; cur += ch
        elif ch == "," and depth == 0:
            args.append(cur); cur = ""
        else:
            cur += ch
    if cur.strip():
        args.append(cur)
    return [a.strip() for a in args]


def rewrite_calls(s, name, fn):
    """Rewrite every FUNC(...) in s using fn(arglist), matching balanced parens."""
    low, nl, out, i = s.lower(), name.lower(), "", 0
    while True:
        j = low.find(nl + "(", i)
        while j > 0 and (s[j - 1].isalnum() or s[j - 1] == "_"):
            j = low.find(nl + "(", j + 1)
        if j == -1:
            return out + s[i:]
        out += s[i:j]
        k, depth = j + len(name) + 1, 1
        while k < len(s) and depth:
            depth += (s[k] == "(") - (s[k] == ")")
            k += 1
        out += fn(_split_args(s[j + len(name) + 1:k - 1]))
        i = k


def clean(n):
    return (n or "").strip("[]")


AGG_RE = re.compile(r"\b(SUM|AVG|COUNT|MIN|MAX)\s*\(", re.I)
# table-calc functions -> the window aggregate they map to
TC_MAP = {"RUNNING_SUM": ("SUM", True), "RUNNING_AVG": ("AVG", True),
          "RUNNING_MAX": ("MAX", True), "RUNNING_MIN": ("MIN", True),
          "WINDOW_SUM": ("SUM", False), "WINDOW_AVG": ("AVG", False),
          "WINDOW_MAX": ("MAX", False), "WINDOW_MIN": ("MIN", False),
          "WINDOW_COUNT": ("COUNT", False), "TOTAL": ("SUM", False)}
TC_RE = re.compile(r"^\s*(" + "|".join(list(TC_MAP) + ["RANK", "INDEX"]) + r")\s*\(", re.I)
DATE_DERIV = {"Year", "Quarter", "Month", "Day", "Week"}


def is_aggregate(sql):
    return bool(AGG_RE.search(sql or ""))


def _datediff(args):
    """DATEDIFF('grain', a, b) -> integer difference in that grain."""
    grain = args[0].strip().strip("'\"").lower() if args else "day"
    a, b = args[1], args[2]
    if grain == "year":
        return f"(EXTRACT(year FROM {b})-EXTRACT(year FROM {a}))"
    if grain == "quarter":
        return (f"((EXTRACT(year FROM {b})*4+EXTRACT(quarter FROM {b}))"
                f"-(EXTRACT(year FROM {a})*4+EXTRACT(quarter FROM {a})))")
    if grain == "month":
        return (f"((EXTRACT(year FROM {b})*12+EXTRACT(month FROM {b}))"
                f"-(EXTRACT(year FROM {a})*12+EXTRACT(month FROM {a})))")
    if grain == "week":
        return f"(floor((({b})::date-({a})::date)/7.0))"
    return f"(({b})::date-({a})::date)"


def parse_fixed(formula):
    """{FIXED [d1],[d2] : AGG} -> ([dim_ids], agg_formula) or None."""
    m = re.match(r"\s*\{\s*FIXED\b(.*)\}\s*$", formula, re.I | re.S)
    if not m:
        return None
    body, depth = m.group(1), 0
    for i, ch in enumerate(body):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == ":" and depth == 0:
            dims = [clean(x) for x in re.findall(r"\[([^\]]+)\]", body[:i])]
            return dims, body[i + 1:].strip()
    return None


def outer_call(formula):
    """('RUNNING_SUM', 'SUM([x])') if formula is exactly one function call."""
    m = re.match(r"\s*([A-Za-z_]+)\s*\(", formula)
    if not m:
        return None
    i, depth = m.end(), 1
    while i < len(formula) and depth:
        depth += (formula[i] == "(") - (formula[i] == ")")
        i += 1
    if formula[i:].strip():
        return None
    return m.group(1).upper(), formula[m.end():i - 1]


# ---------------------------------------------------------------- calc resolver
class Resolver:
    """Resolve a Tableau field id/formula to a Postgres SQL fragment.
    Substitutes parameter current-values so switcher calcs (CASE [Param]...) fold
    to concrete SQL; flags LOD / table-calc / unresolved-parameter formulas."""
    def __init__(self, columns, formulas, params):
        self.cols = columns          # id -> {caption, role, datatype}
        self.formulas = formulas     # id -> formula string
        self.params = params         # cleaned name -> SQL literal
        self.cache = {}
        self.lod_alias = {}          # FIXED-LOD id -> column alias (set during LOD build)
        self.fixed = {}              # FIXED-LOD id -> (dim_ids, agg_formula)
        for cid, f in formulas.items():
            pf = parse_fixed(f)
            if pf:
                self.fixed[cid] = pf

    def col_sql(self, ident):
        cid = clean(ident)
        if cid in self.lod_alias:                 # FIXED LOD -> its window column
            return self.lod_alias[cid], False
        if cid in self.cols and cid not in self.formulas:
            return f'"{self.cols[cid]["caption"]}"', False
        if cid in self.formulas:
            return self.resolve(cid)
        return f'"{cid}"', False

    def translate_leaf(self, formula):
        """Translate an expression, mapping AGG([fixed-lod]) -> MAX(its column)
        (a FIXED LOD at/above the viz grain is constant within the group)."""
        for fid in self.fixed:
            formula = re.sub(rf"(SUM|AVG|MIN|MAX|ATTR)\s*\(\s*\[{re.escape(fid)}\]\s*\)",
                             f'MAX({self.lod_alias.get(fid, "lod_" + fid)})', formula, flags=re.I)
        return self.translate(formula)

    def resolve(self, cid):
        cid = clean(cid)
        if cid in self.cache:
            return self.cache[cid]
        f = self.formulas.get(cid)
        if f is None:
            return self.col_sql(cid)
        self.cache[cid] = (f'"{cid}"', True)   # recursion guard
        sql, hard = self.translate(f)
        self.cache[cid] = (sql, hard)
        return sql, hard

    def translate(self, f):
        hard = bool(HARD.search(f))
        s = re.sub(r"//[^\n]*", "", f)
        s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
        # Tableau string literals "x" -> 'x' ; date literals #d# -> DATE 'd'
        s = re.sub(r'"([^"]*)"', lambda m: "'" + m.group(1).replace("'", "''") + "'", s)
        s = re.sub(r"#(\d{4}-\d{2}-\d{2})#", r"DATE '\1'", s)
        # parameter current-values  [Parameters].[x] -> literal
        def prepl(m):
            v = self.params.get(clean(m.group(1)))
            return v if v is not None else "__PARAM__"
        s = re.sub(r"\[Parameters\]\.\[([^\]]+)\]", prepl, s)
        # field references -> resolved SQL (propagate the referenced calc's hard flag)
        refhard = [False]

        def refrepl(m):
            sub, h = self.col_sql(m.group(1))
            if h:
                refhard[0] = True
            return sub
        s = re.sub(r"\[(?!Parameters)([^\]]+)\]", refrepl, s)
        hard = hard or refhard[0]
        # IF/ELSEIF -> CASE WHEN
        if re.search(r"\bIF\b", s, re.I):
            s = re.sub(r"\bELSEIF\b", "WHEN", s, flags=re.I)
            s = re.sub(r"\bIF\b", "CASE WHEN", s, flags=re.I)
        # functions
        s = re.sub(r"DATETRUNC\('(\w+)',", r"date_trunc('\1',", s, flags=re.I)
        s = re.sub(r"DATEPART\('(\w+)',", r"EXTRACT(\1 FROM ", s, flags=re.I)
        # DATEDIFF('grain', a, b) -> integer grain difference
        s = rewrite_calls(s, "DATEDIFF", _datediff)
        s = re.sub(r"\bYEAR\(", "EXTRACT(year FROM ", s, flags=re.I)
        s = re.sub(r"\bMONTH\(", "EXTRACT(month FROM ", s, flags=re.I)
        s = re.sub(r"\bQUARTER\(", "EXTRACT(quarter FROM ", s, flags=re.I)
        s = re.sub(r"\bDAY\(", "EXTRACT(day FROM ", s, flags=re.I)
        s = re.sub(r"\bCOUNTD\(", "COUNT(DISTINCT ", s, flags=re.I)
        s = re.sub(r"\bZN\(", "(", s, flags=re.I)          # ZN(x) ~ x (SUM ignores nulls)
        # string / cast / date-construct functions (balanced-paren rewrite)
        for _ in range(6):
            prev = s
            s = rewrite_calls(s, "STR", lambda a: f"({a[0]})::text")
            s = rewrite_calls(s, "FLOAT", lambda a: f"({a[0]})::double precision")
            s = rewrite_calls(s, "MID", lambda a: f"substring(({a[0]}) from ({a[1]})"
                              + (f" for ({a[2]})" if len(a) > 2 else "") + ")")
            s = rewrite_calls(s, "MAKEDATE",
                              lambda a: f"make_date(({a[0]})::int,({a[1]})::int,({a[2]})::int)")
            if s == prev:
                break
        # string concatenation: Tableau + -> SQL || (only around string operands)
        s = s.replace("::text +", "::text ||")
        s = re.sub(r"\+\s*'", "|| '", s)
        s = re.sub(r"'\s*\+", "' ||", s)
        s = re.sub(r"\bTrue\b", "true", s)
        s = re.sub(r"\bFalse\b", "false", s)
        s = s.replace("/", "*1.0/")        # Tableau '/' is always float division
        if "__PARAM__" in s:
            hard = True
            s = s.replace("__PARAM__", "NULL")
        if "{" in s and not self.lod_alias:   # a LOD leaked through unresolved
            hard = True
        return s.strip(), hard


# ---------------------------------------------------------------- parsing
def parse_columns(root):
    cols = {}
    for c in root.iter("column"):
        cid = clean(c.get("name"))
        if not cid:
            continue
        cols[cid] = {"caption": c.get("caption") or cid,
                     "role": c.get("role", ""), "datatype": c.get("datatype", "")}
    return cols


def parse_parameters(root):
    """Cleaned param name -> SQL literal of its current value."""
    p = {}
    for c in root.iter("column"):
        if c.get("param-domain-type") is None:
            continue
        name, v, dt = clean(c.get("name")), c.get("value"), c.get("datatype", "")
        if v is None:
            continue
        if dt in ("integer", "real"):
            lit = v
        elif dt == "boolean":
            lit = "true" if str(v).lower() == "true" else "false"
        elif dt == "date":
            m = re.search(r"(\d{4}-\d{2}-\d{2})", v)
            lit = f"DATE '{m.group(1)}'" if m else "NULL"
        else:
            lit = "'" + v.strip('"').replace("'", "''") + "'"
        p[name] = lit
    return p


def sheet_fields(ws, res, cols, formulas):
    """(measures, dims) for a worksheet — measures carry resolved SQL.
    A referenced field is a MEASURE if it is an agg-derivation on a raw column,
    or a calc that resolves to an aggregate expression; otherwise a dimension."""
    meas, dims, seen = [], [], set()
    for ci in ws.iter("column-instance"):
        col = clean(ci.get("column"))
        deriv = ci.get("derivation") or "None"
        if not col or col.startswith(":"):
            continue
        key = (col, deriv)
        if key in seen:
            continue
        seen.add(key)
        caption = cols.get(col, {}).get("caption", col)
        raw = formulas.get(col, "")
        if col in formulas:
            sql, hard = res.resolve(col)
        else:
            sql, hard = f'"{caption}"', False
        if col in res.fixed:                                   # FIXED LOD: dim vs measure by usage
            if deriv in AGG_FN:
                meas.append({"label": caption, "sql": sql, "hard": True, "formula": raw, "col": col})
            else:
                dims.append({"label": caption, "expr": None, "deriv": None, "hard": True, "col": col})
        elif is_aggregate(sql):                                # calc measure
            meas.append({"label": caption, "sql": sql, "hard": hard, "formula": raw, "col": col})
        elif deriv in AGG_FN:                                   # raw agg measure
            meas.append({"label": f"{deriv.upper()}({caption})", "col": col,
                         "sql": f"{AGG_FN[deriv]}({sql})", "hard": hard, "formula": "", "agg": AGG_FN[deriv]})
        elif deriv in ("Year", "Quarter", "Month", "Day", "Week"):
            dims.append({"label": caption, "expr": sql if col in formulas else None,
                         "deriv": deriv, "hard": hard, "col": col})
        else:
            dims.append({"label": caption, "expr": sql if col in formulas else None,
                         "deriv": None, "hard": hard, "col": col})
    return meas, dims


def shelf_dims(ws, cols, res):
    """The dimension pills actually on rows/cols shelves (the true group-by),
    excluding measure-aggregation pills. Returns list of dim dicts."""
    inst = {ci.get("name"): (clean(ci.get("column")), ci.get("derivation") or "None")
            for ci in ws.iter("column-instance")}
    out, seen = [], set()
    for tag in ("rows", "cols"):
        el = ws.find(f".//{tag}")
        if el is None or not el.text:
            continue
        for nm in re.findall(r"(\[[^\]]+\])", el.text):
            if nm in inst:
                col, deriv = inst[nm]
                if col and not col.startswith(":") and deriv not in AGG_FN and col not in seen:
                    seen.add(col)
                    out.append({"label": cols.get(col, {}).get("caption", col),
                                "col": col, "deriv": deriv, "expr": None, "hard": False})
    return out


def _refs(formula):
    return [clean(x) for x in re.findall(r"\[(?!Parameters)([^\]]+)\]", formula or "")]


def uses_fixed(col, res, seen=None):
    """True if col transitively references any FIXED LOD."""
    seen = seen or set()
    if col in seen:
        return False
    seen.add(col)
    if col in res.fixed:
        return True
    for r in _refs(res.formulas.get(col, "")):
        if uses_fixed(r, res, seen):
            return True
    return False


def _needed_fixed(col, res, acc):
    for r in _refs(res.formulas.get(col, "")):
        _needed_fixed(r, res, acc)
    if col in res.fixed:
        acc.append(col)
        for d in res.fixed[col][0]:
            _needed_fixed(d, res, acc)
        for r in _refs(res.fixed[col][1]):
            _needed_fixed(r, res, acc)


def build_lod_dataset(base, viz_dims, measures, filter_sql, res, cols):
    """Layered-CTE virtual dataset that materialises FIXED LODs as window columns,
    then aggregates by the viz dimensions. Returns (sql, x, parts, mlabels)."""
    order = []
    for f in [d["col"] for d in viz_dims] + [m["col"] for m in measures]:
        _needed_fixed(f, res, order)
    seen, ordered = set(), []
    for f in order:                       # dependency order, de-duped
        if f not in seen:
            seen.add(f); ordered.append(f)
    if not ordered:
        return None

    res.lod_alias = {}
    where = f"WHERE {filter_sql}" if filter_sql else ""
    ctes = [f"c0 AS (SELECT * FROM public.{base} {where})"]
    prev, idx = "c0", 1
    for fid in ordered:
        dim_ids, agg = res.fixed[fid]
        parts = [res.col_sql(d)[0] for d in dim_ids]
        agg_sql = res.translate_leaf(agg)[0]
        pby = "PARTITION BY " + ", ".join(parts) if parts else ""
        cd = re.match(r"COUNT\(DISTINCT (.+)\)\s*$", agg_sql.strip(), re.I)
        if cd:   # COUNT(DISTINCT x) OVER (…) is unsupported -> dense_rank trick
            x = cd.group(1)
            win = (f"(dense_rank() OVER ({pby} ORDER BY {x}) + "
                   f"dense_rank() OVER ({pby} ORDER BY {x} DESC) - 1)")
        else:
            win = f"{agg_sql} OVER ({pby})"
        ctes.append(f"c{idx} AS (SELECT *, {win} AS lod_{fid} FROM {prev})")
        res.lod_alias[fid] = f"lod_{fid}"
        prev, idx = f"c{idx}", idx + 1

    def dim_expr(d):
        cid = d["col"]
        if cid in res.fixed:
            return res.lod_alias[cid]
        if cid in res.formulas:
            return res.translate_leaf(res.formulas[cid])[0]
        return f'"{cols.get(cid, {}).get("caption", cid)}"'

    dsel, aliases = [], []
    for i, d in enumerate(viz_dims):
        a = re.sub(r"[^a-z0-9]+", "_", d["label"].lower()).strip("_") or f"d{i}"
        dsel.append(f"{dim_expr(d)} AS {a}")
        aliases.append((a, d))
    msel, mlabels = [], []
    for i, m in enumerate(measures):
        a = re.sub(r"[^a-z0-9]+", "_", m["label"].lower()).strip("_") or f"m{i}"
        if m["col"] in res.formulas:
            expr = res.translate_leaf(res.formulas[m["col"]])[0]
        else:
            expr = f'{m.get("agg", "SUM")}("{cols.get(m["col"], {}).get("caption", m["col"])}")'
        msel.append(f"{expr} AS {a}")
        mlabels.append(a)
    gb = ", ".join(str(i + 1) for i in range(len(aliases)))
    sql = (f"WITH {', '.join(ctes)} SELECT {', '.join(dsel + msel)} "
           f"FROM {prev}" + (f" GROUP BY {gb}" if aliases else ""))
    res.lod_alias = {}
    # x-axis: a temporal / elapsed dim if present, else first
    x = aliases[0][0] if aliases else None
    for a, d in aliases:
        if d.get("deriv") or re.search(r"elapsed|date|month|quarter|day|week", a):
            x = a; break
    parts = [a for a, _ in aliases if a != x]
    return sql, x, parts, mlabels


def mark_of(ws):
    marks = [m.get("class") for m in ws.iter("mark")]
    for pref in ("VizExtension", "Pie", "Line", "Bar", "GanttBar", "Square",
                 "Circle", "Shape", "Area", "Text"):
        if pref in marks:
            return pref
    return marks[0] if marks else "Automatic"


def map_viz(mark, nmeas, ndim, has_geo):
    if mark == "VizExtension":
        return "table", "viz-extension → data table (no Superset equivalent)"
    if has_geo:
        return "deck_scatter", None
    if mark == "Pie":
        return "pie", None
    if mark in ("Line", "Area"):
        return "echarts_timeseries_line", None
    if mark in ("Bar", "GanttBar"):
        return ("echarts_timeseries_bar", None) if ndim else ("big_number_total", None)
    if mark == "Square" and ndim >= 2:
        return "heatmap_v2", None
    if nmeas >= 1 and ndim == 0:
        return "big_number_total", None
    if nmeas >= 1 and ndim >= 1:
        return "echarts_timeseries_bar", None
    return "table", "fallback"


def build_tablecalc(base, func, inner_sql, dims, filter_sql):
    """Build a virtual-dataset SQL that pre-aggregates by the sheet dims then
    applies a window function for the table calc. Returns (sql, x, parts, mcol)."""
    defs = []
    for i, d in enumerate(dims):
        expr = d["expr"] if d.get("expr") else f'"{d["label"]}"'
        alias = re.sub(r"[^a-z0-9]+", "_", d["label"].lower()).strip("_") or f"d{i}"
        defs.append((alias, expr, d))
    if not defs:
        return None
    where = f"WHERE {filter_sql}" if filter_sql else ""
    sel = ", ".join(f"{e} AS {a}" for a, e, _ in defs)
    inner = (f"SELECT {sel}, {inner_sql} AS m FROM public.{base} {where} "
             f"GROUP BY {', '.join(str(i + 1) for i in range(len(defs)))}")
    aliases = [a for a, _, _ in defs]
    order = None
    for a, e, d in defs:
        if d.get("deriv") in DATE_DERIV or re.search(r"date|month|quarter|elapsed|day|week|index|order|rank", a):
            order = a
            break
    part = [a for a in aliases if a != order]
    if func in TC_MAP:
        agg, running = TC_MAP[func]
        over = f"PARTITION BY {', '.join(part)}" if part else ""
        if running and order:
            over = (over + " " if over else "") + f"ORDER BY {order}"
        win = f"{agg}(m) OVER ({over})"
    elif func == "RANK":
        over = f"PARTITION BY {', '.join(part)} " if part else ""
        win = f"RANK() OVER ({over}ORDER BY m DESC)"
    else:  # INDEX
        over = f"PARTITION BY {', '.join(part)} " if part else ""
        win = f"ROW_NUMBER() OVER ({over}ORDER BY {order or aliases[0]})"
    sql = f"SELECT {', '.join(aliases)}, {win} AS val FROM ({inner}) t"
    return sql, (order or aliases[0]), part, "val"


def pick_dashboard(root, want):
    dashes = list(root.iter("dashboard"))
    if want:
        for d in dashes:
            if want.lower() in (d.get("name") or "").lower():
                return d
    # else the dashboard with the most worksheet-zones (the "overview")
    best, bn = None, -1
    for d in dashes:
        n = len([z for z in d.iter("zone") if z.get("name")])
        if n > bn:
            best, bn = d, n
    return best


def layout_rows(zones):
    """Map Tableau zone x/y/w/h (0-100000) to Superset 12-col rows."""
    Z = sorted(zones, key=lambda z: (int(z["y"]), int(z["x"])))
    rows, cur, cy = [], [], None
    for z in Z:
        if cy is None or int(z["y"]) - cy > 4000:   # new visual row
            if cur:
                rows.append(cur)
            cur, cy = [z], int(z["y"])
        else:
            cur.append(z)
    if cur:
        rows.append(cur)
    out = []
    for r in rows:
        tot = sum(int(z["w"]) for z in r) or 1
        row = []
        for z in r:
            w = max(2, min(12, round(int(z["w"]) / tot * 12)))
            h = max(20, min(80, round(int(z["h"]) / 100000 * 100)))
            row.append({**z, "gw": w, "gh": h})
        out.append(row)
    return out


def main(twbx, want=None):
    tmp = tempfile.mkdtemp()
    zipfile.ZipFile(twbx).extractall(tmp)
    twb = glob.glob(f"{tmp}/**/*.twb", recursive=True)[0]
    root = ET.parse(twb).getroot()

    cols = parse_columns(root)
    formulas = migrate.calc_formulas(root)
    inst = migrate.build_instance_map(root)
    params = parse_parameters(root)
    res = Resolver(cols, formulas, params)
    geo_cols = {c["caption"].lower() for c in cols.values()}
    has_geo_ds = ("latitude" in geo_cols and "longitude" in geo_cols)

    base_table = "eng_" + re.sub(r"[^a-z0-9]+", "_", os.path.basename(twbx).lower()).strip("_")[:24]
    dash = pick_dashboard(root, want)
    zones = [{"ws": z.get("name"), "x": z.get("x"), "y": z.get("y"),
              "w": z.get("w"), "h": z.get("h")}
             for z in dash.iter("zone") if z.get("name") and z.get("x")]
    ws_by_name = {w.get("name"): w for w in root.iter("worksheet") if w.get("name")}

    charts, calc_cols = [], {}
    for row in layout_rows(zones):
        for z in row:
            ws = ws_by_name.get(z["ws"])
            if ws is None:
                continue
            meas, dims = sheet_fields(ws, res, cols, formulas)
            mark = mark_of(ws)
            rows_el, cols_el = ws.find(".//rows"), ws.find(".//cols")
            has_shelf = bool((rows_el is not None and rows_el.text) or
                             (cols_el is not None and cols_el.text))
            geo = has_geo_ds and any(d["label"].lower() in ("latitude", "longitude")
                                     for d in dims)
            viz, flag = map_viz(mark, len(meas), len(dims), geo)
            # a sheet with no dimension on rows/cols and a measure = a single value
            single = (not has_shelf and any(not m["hard"] for m in meas) and not geo)
            if single:
                viz, dims = "big_number_total", []
            # drop only the hard measures; keep the resolvable ones (partial migration)
            mlist = [{"label": m["label"], "sql": m["sql"]} for m in meas if not m["hard"]]
            dim_hard = False
            dlist = []
            for d in dims:
                if d["hard"]:
                    dim_hard = True
                    continue
                if d["expr"] and not is_aggregate(d["expr"]):     # calc dimension
                    cc = "cc_" + hashlib.md5(d["label"].encode()).hexdigest()[:8]
                    calc_cols[cc] = d["expr"]
                    dlist.append(cc)
                else:
                    dlist.append(d["label"])
            # keep only filters on physical columns (calc-based filters -> drop,
            # they'd reference fields that don't exist in the loaded table)
            phys = {cid for cid in cols if cid not in formulas} | \
                   {c["caption"] for cid, c in cols.items() if cid not in formulas}
            filters = [f for f in migrate.parse_filters(ws, inst) if f["col"] in phys]
            fsql = migrate.where_sql(filters)

            dataset_sql = None
            # --- Pass 3a: FIXED-LOD -> layered-CTE window SQL ---
            if (any(uses_fixed(d["col"], res) for d in dims)
                    or any(uses_fixed(m["col"], res) for m in meas)):
                vdims = shelf_dims(ws, cols, res)
                vcols = {d["col"] for d in vdims}
                lod_meas = [m for m in meas if m["col"] not in res.fixed
                            and m["col"] not in vcols]
                if vdims and lod_meas:
                    built = build_lod_dataset(base_table, vdims, lod_meas, fsql, res, cols)
                    if built and built[3]:
                        dataset_sql, xdim, parts, mlabels = built
                        viz = ("heatmap_v2" if len(vdims) >= 2 else "echarts_timeseries_line")
                        mcol = mlabels[-1]
                        mlist = [{"label": mcol, "sql": f'MAX("{mcol}")'}]
                        dlist = [xdim] + parts
                        dim_hard = False

            # --- Pass 3b: table-calc -> window SQL via a virtual dataset ---
            tc = next((m for m in meas if not m["hard"] and m.get("formula")
                       and TC_RE.match(m["formula"])), None)
            good_dims = [d for d in dims if not d["hard"]]
            if tc and good_dims and not dataset_sql:
                oc = outer_call(tc["formula"].strip())
                if oc:
                    func, inner = oc
                    inner_sql, ih = (res.translate(inner) if inner.strip()
                                     else ("COUNT(*)", False))
                    if not ih and (is_aggregate(inner_sql) or func == "INDEX"):
                        built = build_tablecalc(base_table, func, inner_sql, good_dims, fsql)
                        if built:
                            dataset_sql, xdim, parts, mcol = built
                            viz = ("echarts_timeseries_line"
                                   if func.startswith("RUNNING") else "echarts_timeseries_bar")
                            mlist = [{"label": tc["label"], "sql": f'MAX("{mcol}")'}]
                            dlist = [xdim] + parts
                            dim_hard = False

            # render-safety guard: never ship a chart that can't draw
            if viz in ("echarts_timeseries_bar", "echarts_timeseries_line") and (
                    not dlist or not dlist[0]):
                viz, dlist = ("big_number_total", []) if mlist else ("table", dlist)
            if viz == "heatmap_v2" and len([d for d in dlist if d]) < 2:
                viz = "echarts_timeseries_line" if mlist and dlist and dlist[0] else "table"

            status, reason = "ok", flag
            if not dataset_sql and (dim_hard or (not mlist and viz not in ("table",))):
                status = "flagged"
                reason = flag or "unresolved LOD/table-calc/parameter — shown as table"
                viz = "table"
            charts.append({"name": z["ws"], "viz_type": viz, "measures": mlist,
                           "dims": dlist, "filter_sql": ("" if dataset_sql else fsql),
                           "dataset_sql": dataset_sql, "status": status,
                           "reason": reason, "gw": z["gw"], "gh": z["gh"],
                           "row_y": int(z["y"])})

    ir = {"workbook": os.path.basename(twbx),
          "dashboard_title": (dash.get("name") or "Migrated") + " (migrated)",
          "dataset": {"calc_columns": calc_cols},
          "charts": charts}
    json.dump(ir, open("ir.json", "w"), indent=2)
    ok = sum(c["status"] == "ok" for c in charts)
    print(f"{ir['workbook']}: dashboard '{dash.get('name')}' -> {len(charts)} charts "
          f"({ok} built, {len(charts)-ok} flagged-as-table)")
    for c in charts:
        m = ",".join(x["label"] for x in c["measures"]) or "-"
        print(f"  [{c['status']:>7}] {c['name']:<26} {c['viz_type']:<24} m={m} d={c['dims']}")
    print("wrote ir.json")
    return ir


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/Users/amaannawab/Desktop/OverviewDashboard.twbx",
         sys.argv[2] if len(sys.argv) > 2 else None)
