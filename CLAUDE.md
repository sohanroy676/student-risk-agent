# CLAUDE.md

@AGENTS.md

## Session context
@memory-bank/projectBrief.md
@memory-bank/activeContext.md
@memory-bank/progress.md

Read on demand: `memory-bank/architecture.md` (module layout, nightly data flow, agent rules), `memory-bank/tech-stack.md` (commands, test locations), `memory-bank/systemPatterns.md`, `ROADMAP.md`, `docs/DETAILED_ROADMAP.md` (per-version tests and expected outcomes), `docs/adr/` (decision records).

## Status
Early stage: the repo currently holds planning docs and config only (no `app/`, `tests/` or `requirements.txt` yet). Build order follows `ROADMAP.md` (v0.1 setup and synthetic data first). Don't assume modules from `architecture.md` exist; check first.

## Commands
- All services: `docker compose up`; migrations: `alembic upgrade head`
- Backend dev: `uvicorn app.main:app --reload`; worker: `celery -A app.jobs worker -l info`; beat: `celery -A app.jobs beat -l info`
- Tests: `pytest`, `pytest evals/` (agent eval set); UI: `cd web && npx playwright test`
- Lint/types: `ruff check . && mypy app`; format: `ruff format .`
- Frontend: `cd web && npm run dev`, `npm run lint`, `npx prettier --check .`

## Hard design rules (do not violate)
- Features use only data dated on or before `as_of`; protected attributes are never model features. Keep the Hypothesis leakage test green.
- Agent tools are read-only plus `save_plan`; tools return case references, never names, roll numbers, phones or protected attributes. Every claim cites a `fact_id`.
- Nothing is sent to a student without mentor approval; the notifier refuses rows without `approved_by`.
- Never expose risk scores or bands to students, parents or faculty (including in API responses and UI for those roles).
- No automated decisions (detention, fines, grades).

## Workflow
Rules live in `.claude/rules/` (security, testing, commit style, self-review, git workflow, session efficiency) and are loaded automatically. Slash commands: `/new-feature`, `/debug`, `/commit` (in `.claude/commands/`). Work on feature branches, never commit to `main`, never push without approval. At the end of a session update `memory-bank/progress.md` and `activeContext.md`.

## Claude API usage
When writing agent code, drafting uses a capable tool-calling model (e.g. `claude-sonnet-5-5`) and follow-up summaries/reply triage a smaller one (e.g. `claude-haiku-5-5`), behind the provider interface in `app/agent/providers/`. API keys come from `.env` only.
