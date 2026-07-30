#!/usr/bin/env python3
"""End-to-end: parse a .twbx -> plan -> apply to Superset -> numeric-diff gate.

Usage: apply_verify.py /path/to/workbook.twbx
"""
import sys, os, json, subprocess
import migrate

CONTAINER = "superset-superset-light-1"
HERE = os.path.dirname(os.path.abspath(__file__))


def sh(*a):
    print("+", " ".join(a))
    subprocess.run(a, check=True)


def main(twbx):
    # 1. parse + plan (writes migration_plan.json in cwd)
    twb, frames = migrate.load_hyper(twbx)
    if not frames:
        print("No packaged extract in this workbook — cannot auto-verify numbers "
              "(live/external source). Structure-only plan below.")
        migrate.main(twbx)
        return
    migrate.main(twbx)

    # 2. export the primary frame for the container
    main_df = max(frames.values(), key=lambda d: d.shape[1])
    pq = "/tmp/mig_primary.parquet"
    main_df.to_parquet(pq)
    print(f"exported primary frame: {main_df.shape[0]:,} rows x {main_df.shape[1]} cols")

    # 3. ship plan + data + container script into the container
    sh("docker", "cp", os.path.join(HERE, "migration_plan.json"),
       f"{CONTAINER}:/tmp/migration_plan.json")
    sh("docker", "cp", pq, f"{CONTAINER}:/tmp/mig_primary.parquet")
    sh("docker", "cp", os.path.join(HERE, "_container_apply.py"),
       f"{CONTAINER}:/tmp/_container_apply.py")

    # 4. run the apply + numeric-diff gate inside the container
    sh("docker", "exec", CONTAINER, "python", "/tmp/_container_apply.py")

    # 5. pull the fidelity report back
    sh("docker", "cp", f"{CONTAINER}:/tmp/fidelity_report.json",
       os.path.join(HERE, "fidelity_report.json"))
    print("\nfidelity_report.json written to spike/")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1
         else "/Users/amaannawab/Desktop/OverviewDashboard.twbx")
