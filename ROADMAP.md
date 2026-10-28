# Roadmap

## Now
- v0.1 Setup and synthetic data: code complete on stacked branches, awaiting review and a Docker verification (see activeContext)
- v0.2 Data and baseline model: OULAD and UCI loaded, as_of feature builder with leakage test, rule score, logistic regression evaluated by week

## Next
- v0.3 Model and explanations (in progress: LightGBM + isotonic calibration done; SHAP reasons, fairness report, MLflow registry and promotion gate to do)
- v0.4 Backend and integration: CSV and Moodle connectors, nightly Celery pipeline, case engine, core APIs, auth and RBAC, audit log
- v0.5 Dashboard: caseload, case detail, faculty flag, admin screens, mentor actions with template drafts
- v0.6 Agent and follow-up: tools, prompt, validator, outbox, 7-day follow-up and escalation, 50-case eval set
- v1.0 Evaluation and release: full metrics, fairness analysis, security review, usability sessions, docs, test at our own college

## Later / ideas
- Optional one-department pilot with real data (needs the college's written permission)
- Optional LangGraph for the agent loop
- Optional Prometheus and Grafana monitoring
- Locally hosted open model if no data may leave campus
- Regression discontinuity analysis around the red threshold to estimate impact

## Explicitly not planned
Nothing is declared out of scope. Design rules: no automated decisions (detention, fines, grades), no showing scores to students or parents, no chat with students beyond replies to an approved message.