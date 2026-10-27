# System Patterns

## Naming conventions
- Python: snake_case modules/functions, PascalCase classes, full type hints (mypy strict on `app` and `data`).
- DB: snake_case, plural table names, schema-qualified (`core.students`); every schema named in tech-stack.md.

## Folder structure logic
- Repo root is the project root (architecture.md's `early-warning/` = this repo).
- `tests/` mirrors `app/` (`tests/db/test_*.py`); generator tests in `tests/synthetic/`.
- `data/synthetic/` is the demo-data generator; output goes to `data/synthetic/out/` (git-ignored).

## Common patterns used in this project
- Config via `app/core/settings.py` (pydantic-settings), values from `.env` only.
- Tests needing Postgres read `TEST_DATABASE_URL` and skip when unset; CI provides it.
- Synthetic generator takes an explicit `seed` and uses one `numpy.random.Generator`; no global RNG.

## Things to avoid
- No secrets in source; no protected attributes outside the `restricted` schema.
- No `git add .`; no commits to `main`.
