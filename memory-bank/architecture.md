# Architecture

## Folder structure
```
early-warning/
  app/
    api/        FastAPI routers: caseload, cases, interventions, admin, webhooks
    core/       settings, auth, RBAC, audit writer
    db/         SQLAlchemy models, Alembic migrations, RLS policies
    ingest/     erp_csv.py, erp_sql.py, moodle.py, cleaners
    features/   build_snapshot(student_ids, as_of), feature registry
    ml/         labels, train, calibrate, explain, fairness, score
    cases/      state machine, timers, rate limits
    agent/      loop, tools, prompts/, schema, validator, providers/
    notify/     outbox, email, whatsapp, sms
    jobs/       Celery tasks and beat schedule
  web/          Next.js app
  data/synthetic/  generator for ERP-shaped demo data
  notebooks/    OULAD and UCI experiments
  evals/        agent eval cases, rubric, runner
  tests/
  docker-compose.yml
```
The backend is one Python codebase of modules; the Next.js app is the only separate part.

## Data flow (nightly, times configurable per college)
1. 01:00 sync ERP and LMS into raw.*, clean into core.*, then build snapshots with as_of = today.
2. 02:30 score every active student: calibrated probability, band (green/amber/red), SHAP, template-rendered reasons.
3. The case engine opens a case for newly red or rapidly rising students and asks the agent for a plan.
4. The agent makes read-only tool calls and saves one validated draft plan.
5. 08:00 the mentor gets a digest, then edits and approves or dismisses each draft.
6. The notifier sends only approved items. Student replies go to the case timeline and are never auto-answered.
7. Day +7 a follow-up check computes success criteria without the LLM; the agent summarises; the mentor resolves, continues or escalates. After two cycles with no change the case escalates to the HoD or counsellor.

## Key modules
- ingest: idempotent upserts into raw, then cleaning into core, plus a nightly data-quality report
- features: point-in-time snapshots using only rows dated on or before as_of; the same code serves training and scoring
- ml: labels, training, isotonic calibration, SHAP explanations, Fairlearn audit, MLflow registry with a promotion gate
- cases: state machine stored in the DB; timers, message caps, hysteresis
- agent: tool loop with read-only tools plus save_plan; output validator; template fallback
- notify: outbox that refuses any row without approved_by
- api: RBAC plus Postgres row-level security; every write is audited
- gov: consent records and a hash-chained append-only audit log

## Agent rules
- Tools are read-only plus save_plan; no tool can send or change records
- Tools return a case reference, never names, roll numbers, phones or protected attributes
- Every claim cites a fact_id; resources are recommended only from the catalog by id
- Nothing reaches a student without mentor approval

## Third-party services and secrets
LLM API, SMTP, WhatsApp Business Cloud API, SMS gateway, Telegram (dev), Moodle Web Services, ERP SQL views or OIDC, Keycloak. All keys and secrets live in `.env` files kept out of git and are never hardcoded. Commit a `.env.example` with variable names only.