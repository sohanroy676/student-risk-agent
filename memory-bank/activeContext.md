# Active Context

## Current focus
v0.2 "Data and baseline model" code is complete and merged to `main`: loaders, `build_snapshot` with Hypothesis leakage test, rule score, weekly logistic regression, richer features, report CLI. **The real-OULAD AUC targets are not met**: week 1 0.680 (target 0.72), week 8 0.781 (target 0.86). Closing that gap is the next task. `setup.md` documents project setup from scratch.

## Recent decisions
- Initial migration includes core ERP tables plus `restricted.student_attributes`; `ml`, `app`, `gov` are empty schemas.
- Synthetic: 15-week term, 5 courses, 3 classes/week, 4 assessments/course, 2 fee instalments, 10% planted struggling (40). Output goes to `data/synthetic/out/` (git-ignored); `python -m data.synthetic.generator`.
- Tests needing Postgres use `TEST_DATABASE_URL` and skip when unset. They run alembic downgrade, so the DB must be a throwaway.
- CI uses `postgresql+psycopg://` URLs and runs plain `mypy` (covers `app` and `data`), `ruff format --check`, alembic, pytest, gitleaks.
- `build_snapshot(tables, student_ids, as_of)` takes `CoreTables` (DataFrames) first; Postgres adapter in `app/features/db.py`. A mark counts only if `submitted_on <= as_of`; a fee paid after `as_of` still counts as overdue; rates are NaN with no data, counts 0. Protected attributes have no path into `CoreTables`.
- OULAD loader: one core course per (module, presentation); a student is one (module, presentation, id_student) registration; banked assessments dropped; undated exams fall back to presentation end; "?" means missing; optional `studentRegistration.csv` (skip students who left by `as_of`) and `vle.csv` (forum/quiz event types); credits and prior attempts go to `student_context`; protected attributes stay in a separate frame.
- UCI loader: static table (no dates), so it cannot feed `build_snapshot`; the file spells "Nacionality", which is treated as protected. Not wired into the report.
- Baseline: fresh logistic regression per week (median impute + scale), train < 2014, test 2014, week N = term start + 7N days.
- Real OULAD AUC (wk1 / wk8): baseline 0.666 / 0.779; with richer features 0.680 / 0.781. A log1p transform of counts gave no gain (0.685 / 0.779), so skew is not the cause. OULAD has no attendance or fee data.
- Datasets live in git-ignored `data/open_university_learning_analytics_dataset/` and `data/predict_students_dropout_and_academic_success/`.

## Blockers / open questions
- Still unverified: `docker compose up` (no Docker on this machine) and `cd web && npm run build`.
- Pinned versions were taken from pip at 2026-10-27; web versions (next 15.5.9 etc.) were not build-tested.
- `tests/features/test_db.py` needs Postgres; verified only by CI.
- The 0.86 week-8 target may be unreachable without demographics, which the design rules forbid. Decide whether to relax the target if features and LightGBM don't close the gap.

## Next step
Close the AUC gap: (1) per-activity-type click features from `vle.csv` (about 20 types, only forum/quiz are split out today), assessment weights; (2) LightGBM (planned in v0.3) vs logistic regression. Then v0.3 "Model and explanations" per `docs/DETAILED_ROADMAP.md`. Next-session prompt is in `memory-bank/nextSessionPrompt.md`.
