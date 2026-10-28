# Active Context

## Current focus
v0.2 "Data and baseline model" code is complete and merged to `main`: loaders, `build_snapshot` with Hypothesis leakage test, rule score, weekly logistic regression, richer features, report CLI. On real OULAD the original AUC targets (0.72 / 0.86) are unreachable without demographics; they were relaxed to week 1 >= 0.68 and week 8 >= 0.79 (still the goal on our own college's data). LightGBM meets them (0.683 / 0.798); logistic regression does not at week 8 (0.779). `setup.md` documents project setup from scratch.

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
- Targets relaxed by the user's decision (2026-10-28): 0.68 week 1, 0.79 week 8 on OULAD. Re-check 0.72 / 0.86 on real college data, which has attendance and fees.
- Dockerfile `libgomp1` (needed by LightGBM) is unverified: no Docker locally.

## v0.3 status (2026-10-28)
- `feature/calibrated-lgbm` done, not pushed. ECE target met every week. The 2x top-10% lift target is structurally out of reach on OULAD: test at-risk rate is 42-48%, so max lift is about 2.1-2.4 (needs ~96% precision at week 1); best result 1.99 at week 8. Decide whether to restate it (e.g. lift vs achievable max, or top-5%) before the promotion gate uses it.
- Calibrated model is fitted on 2013B only (2013J is the validation set), costing 0.01-0.03 AUC versus plain LightGBM. Gate on week-4 AUC should compare calibrated candidates with each other.
- Remaining v0.3 branches: `feature/shap-reasons`, `feature/fairness-report`, `feature/model-registry-gate`.

## Next step
Review and merge the stacked v0.2 branches plus `feature/lightgbm-compare` and `fix/drop-activity-features` (merge summary given in chat). Then v0.3 "Model and explanations" per `docs/DETAILED_ROADMAP.md` (LightGBM is already available via `app/ml/baseline.py` `MODELS`). Real OULAD test AUC, logreg / LightGBM: wk1 0.680 / 0.683, wk2 0.677 / 0.681, wk4 0.719 / 0.740, wk6 0.748 / 0.772, wk8 0.779 / 0.798. Per-activity-type click features and assessment weights were tried and dropped (no gain; activity features reverted in `b066aae`). Demographics must not be added.
