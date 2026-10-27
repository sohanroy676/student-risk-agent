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
- OULAD loader: a student is one (module, presentation, id_student) registration; banked assessments dropped; exams without a date fall back to presentation end; protected attributes returned in a separate frame.
- UCI loader: static table (no dates), so it cannot feed `build_snapshot`; used only as a baseline cross-check.
- Snapshot builder: a mark counts only if `submitted_on <= as_of` (no graded-on date exists), a fee paid after `as_of` still counts as overdue, rates are NaN with no data and counts 0. Rows with a mark but no submission date are treated as unknown. `build_snapshot` takes `CoreTables` as its first argument so the leakage test needs no database.
- OULAD: one core course per (module, presentation); otherwise students would pair with other presentations' assessments.
- Baseline: a fresh logistic regression per week (median impute + scale), trained on presentations before 2014 and tested on 2014; evaluation skips students who unregistered on or before `as_of` (loader reads optional `studentRegistration.csv`). Rule score returns per-rule contributions.
- Real OULAD (2013 train / 2014 test, registered students only): baseline AUC wk1 0.666, wk8 0.779; with richer features 0.680 / 0.781. A log1p transform of counts gave no gain (0.685 / 0.779), so skew is not the cause. OULAD lacks attendance/fees. Untried: per-activity-type clicks (vle.csv types beyond forum/quiz), assessment weights, LightGBM (v0.3), demographics (excluded by design as protected).

## Blockers / open questions
- Still unverified: `docker compose up` (no Docker on this machine) and `cd web && npm run build`.
- Pinned versions were taken from pip at 2026-10-27; web versions (next 15.5.9 etc.) were not build-tested.
- `tests/features/test_db.py` has never run (no local Postgres); verify on the first CI run.

- Real-data AUC targets (week 1 >= 0.72, week 8 >= 0.86) are measured and NOT met; v0.2 stays in ROADMAP "Now".

## Next step
v0.2 code is complete on `feature/dataset-loaders` -> `feature/snapshot-builder` -> `feature/baseline-models`. Branches are stacked on `docs/post-v0.1`; review before merging. Run both loaders on the real OULAD and UCI files once downloaded and fix any schema surprises.
