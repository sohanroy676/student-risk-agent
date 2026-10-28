# Active Context

## Current focus
v0.3 "Model and explanations" is merged to `main` (PR #3) and tagged `v0.3.0`; CI green on the merge commit `fabe83d`. It adds: isotonic-calibrated LightGBM (`app/ml/calibrate.py`), TreeSHAP reasons with `fact_id`s (`explain.py`, `reasons.py`), Fairlearn audit (`fairness.py`), promotion gate, MLflow registry, model card and `python -m app.ml.release` (`gate.py`, `registry.py`, `card.py`, `release.py`). v0.2 (`v0.2.0`) holds the loaders, `build_snapshot` and baselines. On real OULAD the original AUC targets (0.72 / 0.86) are unreachable without demographics; they were relaxed to week 1 >= 0.68 and week 8 >= 0.79 (still the goal on our own college's data). `setup.md` documents project setup from scratch.

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
- `tests/features/test_db.py` needs Postgres; CI passes it (run on PR #3 and the merge commit).
- Targets relaxed by the user's decision (2026-10-28): 0.68 week 1, 0.79 week 8 on OULAD. Re-check 0.72 / 0.86 on real college data, which has attendance and fees.
- Dockerfile `libgomp1` (needed by LightGBM) is unverified: no Docker locally.

## v0.3 decisions
- Calibration: model fitted on earlier training presentations (2013B), isotonic map on the latest (2013J), test year untouched. Real OULAD ECE 0.040 / 0.035 / 0.020 / 0.017 / 0.017 (wk1/2/4/6/8). Calibrated AUC 0.667 / 0.670 / 0.701 / 0.736 / 0.770, below plain LightGBM because the model sees only 2013B.
- Top-10% precision target restated to `min(2x base rate, 0.70)`: 2x is unreachable at OULAD's 42-48% base rate. Set after seeing results; the college's ~10% base rate keeps the 2x rule. Achieved 0.72-0.83.
- Reasons are value-only sentences (no direction), so a low-risk student can get "90 quiz interactions so far". Show reasons only for flagged cases; add direction wording after mentor feedback. SHAP comes from LightGBM `pred_contrib` (no `shap` dependency).
- Fairness flag rule is a placeholder: top 20% of the test cohort by raw score, one cut-off. Week-4 recall gaps: gender 0.005, disability 0.005, region 0.105, imd_band 0.106, age_band 0.138, highest_education 0.155 (limit 0.10); the age gap comes from the 55+ group (n=118). Overall recall is 0.32 at 20% flagged.
- Gate: blocks `auc_lower`, `ece_high`, `gap_high:<attr>`; a named `SignOff` must list the blocks it covers; missing metrics and unassessed attributes are never overridable. On OULAD the model is blocked until a sign-off covers the four gaps. Gate compares calibrated week-4 AUC. MLflow store is local sqlite under `mlruns/` (git-ignored); registry tests take ~110 s.
- Still manual for v0.3: read a model card (`python -m app.ml.release --oulad data/open_university_learning_analytics_dataset --store <dir>`) and the reasons for 10 example students.

## v0.4 decisions (2026-10-28)
- Plan order and answers: bands by calibrated-probability thresholds (e.g. red >= 0.5, amber >= 0.3) with a per-mentor daily cap on new red cases, then re-run fairness audit and gate on the red band; reasons for flagged (amber/red) cases only, mentor-only, direction wording later; keep the 0.10 recall-gap limit and use scoped named sign-offs; Moodle connector deferred; JWT verifier first (tested with a local key), Keycloak later.
- CSV connector: raw layer is all-text, keyed by the table's natural key, last row wins; cleaner rejects (never repairs) bad rows and cascades through foreign keys; exact duplicate rows are dropped silently, conflicting duplicates keep the later row. Report thresholds are untuned defaults: fail if an essential table is empty or >5% of a table's rows are rejected; warn on any issue or attendance/LMS data older than 3 days (marks and fees arrive in bursts, so they are not freshness-checked).
- Rows removed from a later file are not deleted from raw/core (connector only adds and updates).

- Case engine defaults (all untuned, in `app/cases/config.py`): red enter/exit 0.50/0.45, amber 0.30/0.25; rapid rise = +0.15 in 7 days and at least amber; 3 new cases per mentor per night (highest probability first, rest deferred and retried); 28-day reopen cooldown unless p >= 0.70; draft due 1 day, mentor review 3 days, follow-up 7 days, a third cycle escalates. Escalation routes to a person; it decides nothing about the student.
- Only a mentor can approve, only the case's own mentor (RBAC proper comes with auth); only the agent saves a plan; only the system runs the day-7 timer.
- Students with no row in `app.mentor_assignments` are reported as unassigned and get no case. Mentor ids are free text for now (OIDC subject later). Nothing populates `app.mentor_assignments` yet (admin API / import still to do).
- Hypothesis found that `unassigned` order depended on input order; now sorted.

## Next step
Merge `feature/case-engine` after CI confirms the Postgres tests (push the branch first, or merge and watch CI; ask). Then `feature/nightly-pipeline`: Celery task chaining ingest, `build_snapshot`, the registry `production` alias (needs a model loader in `registry.py`), scoring, `run_night`, `run_timers`. The fairness audit and gate still need re-running on the red band (decision 1). Demographics must not be added as features.
