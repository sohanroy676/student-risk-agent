# Active Context

## Current focus
v0.1 "Setup and synthetic data" is merged to `main` (PR #1) and tagged `v0.1.0`. CI is green on main, including the live Alembic migration test on Postgres 16. Next: v0.2 "Data and baseline model" (loaders, `build_snapshot`, rule score, logistic regression by week).

## Recent decisions
- Initial migration includes core ERP tables plus `restricted.student_attributes`; `ml`, `app`, `gov` are empty schemas.
- Synthetic: 15-week term, 5 courses, 3 classes/week, 4 assessments/course, 2 fee instalments, 10% planted struggling (40). Output goes to `data/synthetic/out/` (git-ignored); `python -m data.synthetic.generator`.
- Tests needing Postgres use `TEST_DATABASE_URL` and skip when unset.
- CI uses `postgresql+psycopg://` URLs and runs plain `mypy` (covers `app` and `data`).
- v0.2 choices: `build_snapshot` has a DataFrame core with a thin DB adapter; OULAD "week N" = course start + 7N days; at-risk label = Withdrawn or Fail; AUC-by-week chart is a matplotlib PNG under `docs/`.
- OULAD and UCI datasets are not in the repo; the user will download them later, so the real-data AUC run (targets: week 1 >= 0.72, week 8 >= 0.86) is deferred. Tests use fixtures and the synthetic generator.

## Blockers / open questions
- Still unverified: `docker compose up` (no Docker on this machine) and `cd web && npm run build`.
- Pinned versions were taken from pip at 2026-10-27; web versions (next 15.5.9 etc.) were not build-tested.

## Next step
Merge `docs/post-v0.1` after review, then build v0.2 one feature branch per item: `feature/dataset-loaders`, `feature/snapshot-builder`, `feature/baseline-models`.
