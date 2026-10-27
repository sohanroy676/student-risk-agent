# Prompt for the next session

Paste this after `/clear` or in a fresh session.

---

Continue the student-risk-agent project. v0.2 is merged to `main` (loaders,
`build_snapshot` + Hypothesis leakage test, rule score, weekly logistic regression,
richer features, `python -m app.ml.report`). `setup.md` explains setup, and the
OULAD / UCI datasets are already in `data/` (git-ignored).

The real-OULAD baseline misses its targets: week-1 AUC 0.680 (target 0.72) and
week-8 AUC 0.781 (target 0.86). Evaluation is train on 2013 presentations, test on
2014, registered students only. A log1p transform of counts did not help.

First, confirm `main` is current (`git pull`), CI is green (`gh run list --branch main`),
and `pytest`, `ruff check .`, `mypy` pass. Read `memory-bank/activeContext.md`, the v0.2
and v0.3 sections of `docs/DETAILED_ROADMAP.md`, and `app/features/snapshot.py`.

Then, one feature branch per item with `/new-feature`, no push or merge without asking:
1. Per-activity-type click features. Extend the OULAD loader so `vle.csv` activity types
   beyond forum and quiz (oucontent, resource, subpage, homepage, url, ...) become event
   types, add matching features to `build_snapshot`, and keep the leakage test green.
   Add assessment weights as a feature if it helps.
2. Compare LightGBM against the logistic regression at weeks 1, 2, 4, 6 and 8 using the
   same report CLI. Report the AUC table and say whether the targets are met.

If the targets are still out of reach without demographics (excluded by design as protected
attributes), do not add them. Give me the numbers and a recommendation on whether to relax
the target, then wait for my decision. Before writing code, give me a short plan and any
questions.
