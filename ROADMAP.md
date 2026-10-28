# Roadmap

## Now
- v0.4 Backend and integration, in progress: CSV connector and data-quality report merged; case engine done on `feature/case-engine` (awaiting review)

## Next
- v0.4 remaining: nightly Celery pipeline, core APIs, audit log, JWT/OIDC auth with RBAC and row-level security, Moodle connector (deferred)
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