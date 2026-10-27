# Active Context

## Current focus
v0.1 "Setup and synthetic data" is code complete on five stacked branches, none pushed or merged.

## Recent decisions
- Branches stacked (each off the previous); merge in order.
- Initial migration includes core ERP tables plus `restricted.student_attributes`; `ml`, `app`, `gov` are empty schemas.
- Synthetic: 15-week term, 5 courses, 3 classes/week, 4 assessments/course, 2 fee instalments, 10% planted struggling (40). Output goes to `data/synthetic/out/` (git-ignored); `python -m data.synthetic.generator`.
- Tests needing Postgres use `TEST_DATABASE_URL` and skip when unset.
- CI uses `postgresql+psycopg://` URLs and runs plain `mypy` (covers `app` and `data`).

## Blockers / open questions
- Docker is not installed on this machine: `docker compose up` health and the live migration test have never run. First CI run on a PR will exercise the migration; compose needs a manual check.
- Pinned versions were taken from pip at 2026-10-27 and web versions (next 15.5.9 etc.) were not build-tested (`npm run build` not run).
- CHANGELOG.md not regenerated (run `/commit` step 7 or regenerate before merge).

## Next step
Review the branches, run `docker compose up` somewhere with Docker, then merge in order; then start v0.2.
