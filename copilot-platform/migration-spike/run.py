#!/usr/bin/env python3
"""run.py — ONE command, ANY .twbx -> a Superset dashboard.

  ./.venv/bin/python run.py /path/to/workbook.twbx [dashboard-name-substring]

engine.py parses the workbook into a generic IR; build_ir.py (generic) turns the
IR into Superset datasets + charts + a dashboard. No per-workbook code.
"""
import sys, os, subprocess
import engine, migrate

CONTAINER = "superset-superset-light-1"
HERE = os.path.dirname(os.path.abspath(__file__))


def sh(*a, **k):
    return subprocess.run(a, check=True, **k)


def main(twbx, want=None):
    ir = engine.main(twbx, want)                       # -> ir.json (+ prints plan)
    twb, frames = migrate.load_hyper(twbx)
    if not frames:
        print("no packaged extract; cannot build data-backed charts"); return
    max(frames.values(), key=lambda d: d.shape[1]).to_parquet("/tmp/eng_primary.parquet")
    for f in ["eng_primary.parquet"]:
        sh("docker", "cp", f"/tmp/{f}", f"{CONTAINER}:/tmp/{f}")
    for f in ["ir.json", "build_ir.py"]:
        sh("docker", "cp", f"{HERE}/{f}", f"{CONTAINER}:/tmp/{f}")
    out = subprocess.run(["docker", "exec", CONTAINER, "python", "/tmp/build_ir.py"],
                         capture_output=True, text=True)
    for ln in out.stdout.splitlines():
        if any(t in ln for t in ("dataset ", "DASHBOARD", "open:", "skip")):
            print("   ", ln)
    if out.returncode:
        print(out.stderr[-1500:])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/Users/amaannawab/Desktop/OverviewDashboard.twbx",
         sys.argv[2] if len(sys.argv) > 2 else None)
