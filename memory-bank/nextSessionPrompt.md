# Prompt for the next session

Paste this after `/clear` or in a fresh session.

---

Continue the student-risk-agent project. v0.2 is merged to `main`, pushed and tagged
`v0.2.0`: loaders, `build_snapshot` + Hypothesis leakage test, rule score, weekly logistic
regression, LightGBM (`MODELS` in `app/ml/baseline.py`), and `python -m app.ml.report
--oulad DIR --model both`. `setup.md` explains setup, and the OULAD / UCI datasets are
already in `data/` (git-ignored).

Where the model stands (real OULAD, train 2013, test 2014, registered students only), test
AUC logreg / LightGBM: wk1 0.680 / 0.680, wk2 0.679 / 0.684, wk4 0.728 / 0.741,
wk6 0.750 / 0.769, wk8 0.781 / 0.796. The targets were relaxed to wk1 >= 0.68 and
wk8 >= 0.79 (week 1 is right at the edge; the original 0.72 / 0.86 stay the goal on the
college's own data). Per-activity-type click features and assessment weights were tried and
gave no gain, so they were dropped. Demographics are protected attributes: never add them
as features.

First, confirm `main` is current (`git pull`), CI is green (`gh run list --branch main`),
and `pytest`, `ruff check .`, `mypy` pass. Read `memory-bank/activeContext.md`, the v0.3
section of `docs/DETAILED_ROADMAP.md`, `app/ml/baseline.py` and `app/features/snapshot.py`.

Then start v0.3 "Model and explanations", one feature branch per item with `/new-feature`,
no push or merge without asking. Suggested order:
1. Promote LightGBM to the production model and add isotonic calibration (ECE <= 0.05,
   top-10% precision >= 2x base rate), fitted on a validation split inside the training
   years, never on the test year.
2. SHAP values and reason templates; every rendered reason cites a `fact_id` and matches
   the underlying feature value (100% tested).
3. Fairlearn report on the protected attributes kept in `data.attributes` (evaluation
   only, never features).
4. MLflow registry, model card and the promotion gate (blocks lower week-4 AUC, ECE above
   0.05, or a group recall gap above 0.10 without sign-off).

Known unverified items: `docker compose up` (and the new `libgomp1` line in the
Dockerfile), `cd web && npm run build`, and the Postgres tests, which only CI runs.

Before writing code, give me a short plan and any questions.
