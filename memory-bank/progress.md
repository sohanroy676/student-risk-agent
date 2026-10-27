# Progress

## Done

- Repo skeleton, ruff/mypy/pytest config, pinned requirements — branch `feature/repo-skeleton`, 2026-10-27
- Docker Compose (Postgres 16, Redis 7, API, web) and `/health` — `feature/docker-compose` (compose NOT run: no Docker locally)
- Alembic + initial migration for 6 schemas and core tables — `feature/alembic-schemas` (live DB test skipped locally)
- Synthetic generator (6 sections, 400 students, 15-week term, 40 planted) with tests — `feature/synthetic-generator`
- CI bootstrap tolerance removed, alembic step added — `fix/ci-remove-bootstrap-tolerance`

## In progress

- v0.1 review and merge (branches are stacked: merge in the order above)
