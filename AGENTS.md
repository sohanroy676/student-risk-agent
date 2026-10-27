# AGENTS.md

Early-warning module for college ERP: scores student risk nightly and drafts mentor-approved interventions.

Stack: Python 3.12, FastAPI, PostgreSQL 16, Celery/Redis, LightGBM, Next.js, Anthropic SDK.

Commands:
- Run: `docker compose up`
- Test: `pytest`
- Lint: `ruff check . && mypy app`
- Format: `ruff format .`

Conventions:
- Never hardcode secrets; use `.env` (kept out of git).
- Features use only data dated on or before as_of; protected attributes are never model features.
- The agent is read-only plus save_plan; nothing is sent to a student without mentor approval.
- Never show risk scores to students, parents or faculty.

Detailed rules are in .claude/rules/ (see also CLAUDE.md).