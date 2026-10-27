# Progress

## Done

- v0.1 merged to `main` (PR #1) and tagged `v0.1.0`; CI green on main (run 40489530319, 2026-10-27)
- Repo skeleton, ruff/mypy/pytest config, pinned requirements
- Docker Compose (Postgres 16, Redis 7, API, web) and `/health` (compose NOT run: no Docker locally)
- Alembic + initial migration for 6 schemas and core tables (live Postgres 16 migration test verified by CI)
- Synthetic generator (6 sections, 400 students, 15-week term, 40 planted) with tests
- CI bootstrap tolerance removed, alembic step added

## In progress

- v0.2 "Data and baseline model", one branch per item, stacked on `docs/post-v0.1` (nothing pushed):
  - `feature/dataset-loaders`: OULAD and UCI loaders done (`app/ingest/oulad.py`, `uci.py`); pandas added. Fixture tests only; real files not yet checked (UCI column names are from memory)

## Next

- `feature/snapshot-builder`: `build_snapshot` with Hypothesis leakage test
- `feature/baseline-models`: rule score and logistic regression by week

## Unverified

- `docker compose up`
- `cd web && npm run build`
