"""Phase-1 runner: parse a .twbx, run the per-tile agent on every measure tile,
print verdicts + a mini fidelity report, then prove the verify gate flags a bad
translation instead of shipping it green (flag, don't fake).

    ../spike/.venv/bin/python -m agent.run_agent [/path/to/workbook.twbx]
(run from the tableau-migration/ directory)
"""

import os
import sys

from . import tools
from .tile_graph import build_tile_graph

DEFAULT = os.path.expanduser("~/Desktop/Superstore.twbx")
ICON = {"GREEN": "✅", "YELLOW": "\U0001f7e8", "RED": "\U0001f7e5"}


def run(twbx):
    root, inst, formulas, frames, primary = tools.load_workbook(twbx)
    print(f"WORKBOOK: {os.path.basename(twbx)}")
    if primary is None:
        print("  no packaged extract (live connection) — Tier-0 data-oracle "
              "unavailable; would fall back to Tier-1 rendered oracle.")
        return
    print(f"  primary frame: rows={len(primary)} cols={primary.shape[1]}  "
          f"tables={list(frames)}\n")

    tiles = [t for t in tools.plan_tiles(root, inst, formulas, frames) if t["measures"]]
    graph = build_tile_graph(primary, llm=None)  # no LLM key -> Fix degrades to flag

    tally = {"GREEN": 0, "YELLOW": 0, "RED": 0}
    for t in tiles:
        out = graph.invoke({"tile": t})
        verdict = out["verdict"]
        tally[verdict] += 1
        print(f'{ICON[verdict]} {t["sheet"]:<22} {verdict:<7} {out["reason"]}')
        for label, d in (out.get("diffs") or {}).items():
            mark = "=" if d["ok"] else "≠"
            print(f'        {label}: oracle={d["expected"]:,.4f} {mark} got={d["got"]}')

    print(f'\nFIDELITY: {tally["GREEN"]} green, {tally["YELLOW"]} yellow, '
          f'{tally["RED"]} red  (of {len(tiles)} measure tiles)')

    _prove_gate(tiles, primary)


def _prove_gate(tiles, primary):
    """Fault-injection: corrupt a green tile's translation and confirm it's flagged."""
    target = next((t for t in tiles if tools.data_oracle(t, primary)
                   and any(m["agg"] == "Sum" for m in t["measures"])), None)
    if not target:
        return
    print(f'\n--- fault injection on "{target["sheet"]}" (swap SUM->AVG) ---')
    orig = tools.translate_sql

    def broken(tile):
        spec = orig(tile)
        spec["select"] = [(lbl, expr.replace("SUM(", "AVG(")) for lbl, expr in spec["select"]]
        return spec

    tools.translate_sql = broken
    try:
        out = build_tile_graph(primary, llm=None).invoke({"tile": target})
    finally:
        tools.translate_sql = orig
    caught = out["verdict"] != "GREEN"
    print(f'    verdict: {out["verdict"]}  ({out["reason"]})')
    print("    -> gate caught the bad translation; nothing shipped green. ✅"
          if caught else "    -> gate MISSED it (bug). ✗")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else DEFAULT)
