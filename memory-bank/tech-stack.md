# Tech Stack

## Languages and frameworks
- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 (Pydantic models double as the agent's output schema)
- Frontend: Next.js (React), Tailwind, Recharts (Streamlit acceptable for early demos)
- ML: pandas or polars, scikit-learn, LightGBM, shap, fairlearn, MLflow (CPU only)
- Agent: Anthropic Python SDK with tool use, behind a thin provider interface (a locally hosted open model is allowed via the same interface)
- Jobs: Celery + Redis, Celery beat for schedules
- Auth: ERP SSO via OIDC if available, otherwise Keycloak
- Node, Next.js, Redis and Celery versions: not pinned yet

## Database and services
- PostgreSQL 16 with row-level security and JSONB; schemas: raw, core, ml, app, gov, restricted
- pgvector (same database) for the resource catalog and policy PDFs
- LLM: drafting uses a capable tool-calling model (e.g. claude-sonnet-5-5); follow-up summaries and reply triage use a smaller model (e.g. claude-haiku-5-5)
- Messaging: SMTP, WhatsApp Business Cloud API, Indian SMS gateway (DLT templates); Telegram as the free dev/demo stand-in
- Data sources: college ERP (SQL views or CSV/Excel export), Moodle Web Services
- Datasets for development: OULAD, UCI dropout dataset, synthetic generator

## Testing
- Backend: pytest; Hypothesis for the feature-leakage test
- UI: Playwright
- Agent: fixed eval set of 50 synthetic cases in evals/
- Location and naming (chosen): tests/ mirrors app/ (tests/features/test_*.py); UI tests in web/e2e/*.spec.ts
- Run (chosen): `pytest`, `pytest evals/`, `cd web && npx playwright test`

## Lint and format (chosen)
- Python: `ruff check .`, `ruff format .`, `mypy app`
- Frontend: `cd web && npm run lint`, `npx prettier --check .`

## Build, run, dev (chosen)
- All services: `docker compose up`
- Migrations: `alembic upgrade head`
- Backend dev: `uvicorn app.main:app --reload`
- Frontend dev: `cd web && npm run dev`
- Worker: `celery -A app.jobs worker -l info`; scheduler: `celery -A app.jobs beat -l info`
- Package manager: pip with a pinned requirements file; npm for web (chosen)

## Ops
- Docker Compose, Nginx, nightly pg_dump backups, optional Prometheus and Grafana
- One campus VM; about 4 vCPU and 8 GB RAM for 5,000 students