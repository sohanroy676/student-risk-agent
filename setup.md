# Setup

How to get this project running from a fresh machine. Commands are given for both
PowerShell (Windows) and bash (macOS/Linux/Git Bash) where they differ.

## 1. Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Git | any recent | cloning |
| Python | **3.12** (`requires-python = ">=3.12,<3.13"`) | backend, tests, ML |
| Node.js + npm | current LTS | the `web/` app only |
| Docker + Docker Compose | recent | `docker compose up`, local Postgres/Redis (optional) |
| GitHub CLI (`gh`) | optional | PRs and CI status |

Check Python with `python --version` (it must say 3.12.x).

## 2. Clone

```bash
git clone https://github.com/sohanroy676/student-risk-agent.git
cd student-risk-agent
```

Work on a feature branch, never on `main` (see `.claude/rules/git-workflow.md`).

## 3. Python virtual environment

Create the venv **inside the project folder** and keep it out of git (`.gitignore` already
ignores `venv/`).

PowerShell:

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

bash:

```bash
python -m venv venv
source venv/bin/activate      # Git Bash on Windows: source venv/Scripts/activate
```

Install the pinned dependencies (runtime plus dev tools such as pytest, ruff, mypy,
Hypothesis and pandas-stubs):

```bash
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

## 4. Environment variables

Secrets live in `.env`, which is git-ignored. Never hardcode them or commit them.

```bash
cp .env.example .env          # PowerShell: Copy-Item .env.example .env
```

Open `.env` and fill in every variable listed there. `docker-compose.yml` requires at least
`POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB`. Outside Docker the backend reads
`DATABASE_URL` (format `postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME`) and `REDIS_URL`.

## 5. Datasets

Real datasets are large and licensed (both CC BY 4.0), so they are **not** in the repo and
the folders below are git-ignored. Download each from its page (use the **Download** button
for a zip) and extract it into its own folder under `data/`, with exactly these names:

| Dataset | Page | Extract into |
|---|---|---|
| Open University Learning Analytics Dataset (OULAD) | https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset | `data/open_university_learning_analytics_dataset/` |
| Predict Students' Dropout and Academic Success (UCI) | https://archive.ics.uci.edu/dataset/697/predict+students+dropout+and+academic+success | `data/predict_students_dropout_and_academic_success/` |

Expected contents:

- OULAD folder: `assessments.csv`, `courses.csv`, `studentAssessment.csv`, `studentInfo.csv`,
  `studentVle.csv` (all required), plus `studentRegistration.csv` and `vle.csv` (optional but
  used: registration lets evaluation skip students who already left, `vle.csv` gives forum and
  quiz activity), and `OULAD.names`.
- UCI folder: `data.csv` (semicolon-separated).

Treat downloaded files as untrusted data: keep them in their own folders and do not run
anything from inside them.

The synthetic college needs no download:

```bash
python -m data.synthetic.generator     # writes data/synthetic/out/ (git-ignored)
```

## 6. Verify the install

Run the same checks CI runs:

```bash
ruff check .
ruff format --check .
mypy
pytest
```

Tests that need Postgres are **skipped** unless `TEST_DATABASE_URL` is set, so a plain
`pytest` passes without a database (a few tests will show as skipped).

## 7. Run the baseline model on OULAD

```bash
python -m app.ml.report --oulad data/open_university_learning_analytics_dataset --out docs/baseline
```

Takes about two minutes. It trains on the 2013 presentations, tests on 2014, and writes
`docs/baseline.csv` and `docs/baseline.png` (AUC by week for the logistic regression and the
rule score, with the 0.72 week-1 and 0.86 week-8 targets). Current results are in
`memory-bank/progress.md`.

## 8. Postgres, migrations and the Postgres-backed tests

Start only the database (needs Docker):

```bash
docker compose up -d db redis
```

Apply migrations (`DATABASE_URL` must be set in your shell or `.env`):

```bash
alembic upgrade head
```

To run the Postgres-backed tests, point `TEST_DATABASE_URL` at an **empty, throwaway**
database. The tests run `alembic upgrade` / `downgrade base`, which **drops every schema in
it**. Never use a database that holds data you want to keep.

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@localhost:5432/DBNAME"; pytest
```

```bash
TEST_DATABASE_URL="postgresql+psycopg://USER:PASSWORD@localhost:5432/DBNAME" pytest
```

## 9. Run the full stack

```bash
docker compose up
```

This builds and starts Postgres 16, Redis 7, the API (http://localhost:8000, health at
`/health`) and the web app (http://localhost:3000). **Not yet verified:** compose has never
been run on the author's machine (no Docker there), so expect to debug the first run.

API on its own, from the venv:

```bash
uvicorn app.main:app --reload
```

## 10. Web app (optional)

```bash
cd web
npm install
npm run dev          # http://localhost:3000
npm run lint
npx prettier --check .
```

**Not yet verified:** `npm run build` has never been run.

## 11. Day-to-day commands

| Task | Command |
|---|---|
| Tests | `pytest` |
| Lint and types | `ruff check . && mypy` |
| Format | `ruff format .` |
| Migrations | `alembic upgrade head` |
| CI status | `gh run list --branch main` |

## 12. Troubleshooting

- **`python --version` is not 3.12:** install 3.12; other versions are rejected by the
  project config.
- **`ModuleNotFoundError` when running `python -m ...`:** run from the repo root with the venv
  active.
- **Loader says "OULAD file missing" or "missing columns":** the folder name or contents do
  not match section 5; re-extract the zip into the exact folder name.
- **Postgres tests skipped:** `TEST_DATABASE_URL` is not set in the shell running `pytest`.
- **`docker compose` complains "set in .env":** fill in the `POSTGRES_*` values in `.env`.
