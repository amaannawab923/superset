#!/usr/bin/env python3
"""ONE command: a .twbx -> a 1:1 Superset dashboard. No screenshot.

  ./.venv/bin/python tableau_to_superset.py /path/to/workbook.twbx

Pipeline (all inputs come from the file):
  1. extract_spec.py  — derive tile logic from the .twb XML
  2. migrate.load_hyper — read the .hyper extract into pandas
  3. load data + build every tile + assemble the dashboard in Superset
"""
import sys, os, subprocess
import migrate, extract_spec

CONTAINER = "superset-superset-light-1"
HERE = os.path.dirname(os.path.abspath(__file__))


def sh(*a, **k):
    return subprocess.run(a, check=True, **k)


def main(twbx):
    print(f"== {os.path.basename(twbx)} ==")

    # 1. derive the tile spec from the .twb (funnel / source group / scale / LODs)
    spec = extract_spec.extract(twbx)
    import json
    json.dump(spec, open(f"{HERE}/derived_spec.json", "w"), indent=2)
    print(f"1. derived spec from XML: funnel={list(spec['funnel']['map'].values())}, "
          f"scale={spec['scale']}, sources={sorted(set(spec['source_group']['map'].values()))}, "
          f"LODs={len(spec['lod_fields'])}, table-calcs={len(spec['tablecalc_fields'])}")

    # 2. read the packaged extract
    twb, frames = migrate.load_hyper(twbx)
    if not frames:
        print("no packaged extract — cannot auto-build (live source)"); return
    df = max(frames.values(), key=lambda d: d.shape[1])
    df.to_parquet("/tmp/mig_primary.parquet")
    print(f"2. read extract: {df.shape[0]:,} rows x {df.shape[1]} cols")

    # 3. ship data + spec + builders into Superset and run
    for f in ["mig_primary.parquet"]:
        sh("docker", "cp", f"/tmp/{f}", f"{CONTAINER}:/tmp/{f}")
    for f in ["migration_plan.json", "derived_spec.json",
              "_container_apply.py", "_container_full_dash.py"]:
        if os.path.exists(f"{HERE}/{f}"):
            sh("docker", "cp", f"{HERE}/{f}", f"{CONTAINER}:/tmp/{f}")
    # (re)generate the plan the loader/apply step expects
    migrate.main(twbx)
    sh("docker", "cp", f"{HERE}/migration_plan.json", f"{CONTAINER}:/tmp/migration_plan.json")

    print("3a. loading data into Superset analytics DB ...")
    sh("docker", "exec", CONTAINER, "python", "/tmp/_container_apply.py",
       stdout=subprocess.DEVNULL)
    print("3b. building tiles + dashboard ...")
    out = subprocess.run(["docker", "exec", CONTAINER, "python",
                          "/tmp/_container_full_dash.py"],
                         capture_output=True, text=True)
    for line in out.stdout.splitlines():
        if any(t in line for t in ("DASHBOARD", "open:", "dimensional gate",
                                   "PASS", "FAIL", "virtual datasets")):
            print("   ", line)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1
         else "/Users/amaannawab/Desktop/OverviewDashboard.twbx")
