\# Detailed Roadmap



Each version lists what is done, what to test (A = automatic, M = manual), and the expected outcome. A version is complete only when all its expected outcomes hold.



\## v0.1 Setup and synthetic data

\*\*Done:\*\* repository and folder layout, Docker Compose (Postgres, Redis, API, web), Alembic migrations for all schemas, CI running lint and tests, synthetic generator (6 sections, 400 students, a full term of attendance, marks, fees, Moodle logs, planted struggling students).

\*\*Test:\*\*

\- A: `docker compose up` brings all services healthy; `alembic upgrade head` runs clean on an empty DB; `ruff check .` and `pytest` pass in CI.

\- A: generator is deterministic for a fixed seed and row counts match the spec.

\- M: open the database and confirm planted struggling students have visibly lower attendance and submissions.

\*\*Expected:\*\* a fresh clone starts with one command and holds a realistic synthetic college.



\## v0.2 Data and baseline model

\*\*Done:\*\* OULAD and UCI loaders, feature builder `build\_snapshot(student\_ids, as\_of)`, rule-based score, logistic regression baseline, evaluation by week.

\*\*Test:\*\*

\- A: leakage test (Hypothesis): build a snapshot, add rows dated after as\_of, rebuild, assert the snapshot is unchanged.

\- A: time-based split (OULAD 2013 train, 2014 test); metrics computed at weeks 1, 2, 4, 6, 8.

\- M: view the AUC-by-week chart and compare with the benchmark.

\*\*Expected:\*\* zero leakage failures; baseline AUC reported per week, AUC of at least 0.68 (week 1) and 0.79 (week 8) on OULAD, relaxed from the blueprint's 0.72 and 0.86 (still the goal on our own college's data).



\## v0.3 Model and explanations

\*\*Done:\*\* LightGBM, isotonic calibration, SHAP, reason templates with fact\_ids, Fairlearn report, MLflow registry, promotion gate.

\*\*Test:\*\*

\- A: calibration error (ECE) at or below 0.05; top-10% precision at least 2x base rate.

\- A: every rendered reason matches the underlying feature values (100%).

\- A: promotion gate blocks a model with a lower week-4 AUC, ECE above 0.05, or a group recall gap above 0.10 without sign-off.

\- M: review a model card and fairness table; read reasons for 10 example students for clarity.

\*\*Expected:\*\* a promoted model with a model card, fairness table, and plain-language reasons that are always true to the data.



\## v0.4 Backend and integration

\*\*Done:\*\* CSV and Moodle connectors, cleaner and data-quality report, nightly Celery pipeline, case engine (states, timers, hysteresis, rate limits), core APIs, OIDC/Keycloak auth, RBAC and row-level security, hash-chained audit log.

\*\*Test:\*\*

\- A: re-running ingest is idempotent (no duplicate rows).

\- A: a mentor token cannot read another mentor's mentees; each role sees only what the visibility table allows.

\- A: tampering with an audit row breaks the hash chain check.

\- A: nightly run on 5,000 synthetic students finishes in under 30 minutes; p95 API latency under 500 ms.

\- M: run the night's job and follow cases through the API docs page.

\*\*Expected:\*\* the nightly job produces scores and cases; access control and audit hold under test.



\## v0.5 Dashboard

\*\*Done:\*\* caseload, case detail, follow-up review, raise concern (faculty), escalations, department overview, models and fairness, resources and settings, audit screens; mentor approve/edit/dismiss with template drafts.

\*\*Test:\*\*

\- A: Playwright flows for each role: mentor approves a draft, faculty raises a concern, admin promotes a model.

\- A: students and faculty cannot see bands or scores.

\- M: a mentor completes a review in under a minute; check layout on laptop and phone widths.

\*\*Expected:\*\* the full mentor workflow works end to end using template messages.



\## v0.6 Agent and follow-up

\*\*Done:\*\* agent tools, prompt, Pydantic plan schema, validator, retry and template fallback, outbox and notifier (email plus Telegram or WhatsApp), reply handling, 7-day follow-up, two-cycle escalation, eval set of 50 synthetic cases.

\*\*Test:\*\*

\- A: eval set: 100% of claims tied to valid fact\_ids; 0 banned-term leaks; 100% of crisis cases routed to people with no student message.

\- A: notifier refuses any row without approved\_by; max one outreach per student per 7 days; quiet hours 21:00 to 08:00 IST enforced; missing consent blocks sending.

\- A: adversarial cases (prompt-injection notes, missing data) do not break the validator.

\- M: a flagged student gets a drafted plan, the mentor approves, the message arrives, and a simulated week later the outcome is checked; blind rating of drafts against a generic-nudge baseline.

\*\*Expected:\*\* safe, grounded drafts; at least 60% approved unchanged and at least 4/5 on the rubric; nothing sent without approval.



\## v1.0 Evaluation and release

\*\*Done:\*\* full metric and fairness runs, agent rubric study, usability sessions with 5 to 10 faculty, security review, documentation, test at our own college.

\*\*Test:\*\*

\- A: all earlier tests green; nightly and latency targets met.

\- M: usability sessions score mentor clarity at least 4/5; security checklist (TLS, encryption, consent, kill switch, retention) signed off.

\- M: run at our college and record results.

\*\*Expected:\*\* a complete prototype with all main features working, with documented results, ready to continue in Claude Code.

