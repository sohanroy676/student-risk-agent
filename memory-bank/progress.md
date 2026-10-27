# Progress

## Done

- v0.1 merged to `main` (PR #1) and tagged `v0.1.0`; CI green on main (run 40489530319, 2026-10-27)
- Repo skeleton, ruff/mypy/pytest config, pinned requirements
- Docker Compose (Postgres 16, Redis 7, API, web) and `/health` (compose NOT run: no Docker locally)
- Alembic + initial migration for 6 schemas and core tables (live Postgres 16 migration test verified by CI)
- Synthetic generator (6 sections, 400 students, 15-week term, 40 planted) with tests
- CI bootstrap tolerance removed, alembic step added

## In progress

- `docs/post-v0.1`: memory-bank and CHANGELOG refresh (not pushed)

## Next

- v0.2 "Data and baseline model": dataset loaders, `build_snapshot` with leakage test, rule score and logistic regression by week

## Unverified

- `docker compose up`
- `cd web && npm run build`
