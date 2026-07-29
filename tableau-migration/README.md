# Tableau → Superset Migration Pipeline

Parses any Tableau `.twbx`, resolves its calc/LOD/table-calc semantics to SQL,
builds the equivalent Superset dashboard, and verifies each tile's numbers
against ground truth computed from the extract.

## Run (one command)
```bash
cd spike && ./.venv/bin/python run.py /path/to/workbook.twbx ["Dashboard name"]
```

## Layout
- `spike/migrate.py` — parse `.twbx`, classify tiles, compute ground truth from the `.hyper`
- `spike/engine.py` — general resolver: parameter unrolling, string/date fns,
  FIXED-LOD → window SQL, table-calc → window SQL; emits a workbook-agnostic IR
- `spike/build_ir.py` — generic IR → Superset datasets + charts + dashboard
- `spike/run.py` — orchestrator (`.twbx` → Superset)
- `spike/extract_spec.py`, `spike/apply_verify.py` — spec derivation + numeric-diff gate
- 1:1 proven builders: `_container_full_dash.py` (Overview), `_container_merch.py`
  (Merchandise), `_container_hr.py` (HR blind-migration experiment)
- `MIGRATION_BUDDY_ARCHITECTURE.md` — LangGraph agent architecture + build plan

## Notes
- The Python venv, extracted `.hyper`, and test `.zip` are intentionally omitted
  (regenerable from the source `.twbx`). Recreate the venv with `pandas pantab
  tableauhyperapi pyarrow` and point `run.py` at a `.twbx`.
- Migrated dashboards are created in the local Superset (docker `bi_spike` DB).
