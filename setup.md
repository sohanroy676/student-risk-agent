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

### Rules that save time

- **Do not leave a line blank if you do not need it. Delete it.** `.env.example` lists every
  name with an empty value, but an empty value is not the same as "not set": it replaces the
  built-in default with an empty string. A blank `APP_TIMEZONE=` makes the API fail with
  `ZoneInfo keys must be normalized relative paths`; a blank `JWT_ROLES_CLAIM=` or `MODEL_STORE=`
  replaces `roles` and `mlruns` with nothing, so role lookup and the model folder go wrong.
  Variables with a default (marked below) can simply
  be removed.
- The app reads `.env` from the folder you start it in, so run commands from the repo root.
  A variable set in your shell wins over the same name in `.env`.
- Never put a real password, key or token anywhere except `.env` (git-ignored) and never paste
  it into chat, issues or commits.
- To make a password: `python -c "import secrets; print(secrets.token_urlsafe(24))"`. It only
  uses letters, digits, `-` and `_`, so it is safe inside a database URL. A password with `@`,
  `:`, `/` or `%` would need URL-encoding there.

### What each variable is

| Variable | Needed for | What to put |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Docker Compose (it creates the database from them) | Any names you choose, e.g. user `risk`, db `risk`, and a generated password. Compose refuses to start without all three. |
| `DATABASE_URL` | API, worker, migrations, `alembic` | `postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME` using the three values above. Use `localhost` as HOST when the app runs on your machine. Inside Compose this is set for you and your `.env` value is ignored. |
| `REDIS_URL` | Celery worker and beat (nightly job) | `redis://localhost:6379/0` for a Redis on your machine. Inside Compose it is set for you. The worker refuses to start without it; the API alone does not need it. |
| `APP_ENV` | Safety switch | `dev` (default). Use `production` on a real server: the dev token tool then refuses to run. |
| `APP_TIMEZONE` | When "tonight" and "today" start | An IANA name such as `Asia/Kolkata`. Default `UTC`. The nightly job runs at 01:00 in this zone. |
| `CSV_DIR` | Nightly job | Folder holding the ERP/LMS CSV exports (see section 5 for the synthetic set: `data/synthetic/out`). Required for the nightly run, not for the API. |
| `MODEL_STORE` | Nightly job and model release | Folder for the local MLflow store. Default `mlruns` (git-ignored). Remove the line unless you want it elsewhere. |
| `JWT_ISSUER`, `JWT_AUDIENCE` | Sign-in checks on every API call | The issuer URL and audience of your identity provider. For local trials any fixed text works, e.g. `https://dev.local` and `risk-api`, as long as the same values are used to mint tokens. |
| `JWT_PUBLIC_KEY` | Sign-in checks | The identity provider's RS256 public key as one line with `\n` where the line breaks are. For local trials, print it with `python -m app.core.dev_token --show-public-key`. Use this **or** `JWT_JWKS_URL`. |
| `JWT_JWKS_URL` | Sign-in checks | The provider's JWKS address, instead of a fixed key. Leave out if you use `JWT_PUBLIC_KEY`. |
| `JWT_ROLES_CLAIM` | Sign-in checks | Where the roles sit in the token. Default `roles`; a dotted path such as `realm_access.roles` works. Remove the line if the default is right. |
| `NEXT_PUBLIC_DEV_TOKEN_LOGIN` | Web sign-in page | `true` shows a paste-a-token form (dev only), anything else hides it. Compose defaults to `false`. Never `true` on a real server. |
| `SECRET_KEY` | Nothing yet | Not read by any code today. You can leave it out for now, or generate a value as above so it is ready. |
| `ANTHROPIC_API_KEY` | Nothing yet | Not read by any code today. It is for the drafting agent planned for v0.6. When that arrives, create a key in the Anthropic Console and keep it only in `.env`. |

Without any `JWT_*` settings the API starts but answers `503 authentication is not configured`
to every call; a wrong key or audience gives a bare `401`.

### A working local setup (app on your machine, Postgres and Redis anywhere reachable)

```text
POSTGRES_USER=risk
POSTGRES_PASSWORD=<generated password>
POSTGRES_DB=risk
DATABASE_URL=postgresql+psycopg://risk:<generated password>@localhost:5432/risk
REDIS_URL=redis://localhost:6379/0
APP_ENV=dev
APP_TIMEZONE=Asia/Kolkata
CSV_DIR=data/synthetic/out
JWT_ISSUER=https://dev.local
JWT_AUDIENCE=risk-api
NEXT_PUBLIC_DEV_TOKEN_LOGIN=true
```

Then add the public key and mint a token (the key pair is created on first use in
`.dev-keys/`, which is git-ignored):

```bash
python -m app.core.dev_token --show-public-key     # copy the printed JWT_PUBLIC_KEY=... line into .env
python -m app.core.dev_token --role mentor --sub m1  # prints a token to paste on the web sign-in page
```

Roles you can mint: `admin`, `staff`, `mentor`, `faculty`. The web app sign-in is dev-only for
now; real single sign-on is not built yet.

**Check your file** without printing any secret. This lists the settings that are empty:

```bash
python -c "from app.core.settings import get_settings as g; print([k for k, v in g().model_dump().items() if v == ''])"
```

An empty `jwt_jwks_url` is fine when you use `JWT_PUBLIC_KEY`, and the other way round.
Anything else listed that you need (for example `app_timezone`, `database_url`) is a blank line
to fill in or delete.

**Docker notes (not yet verified, no Docker on the author's machine):**
- Changing `POSTGRES_*` after the first start does not change the existing database; the
  password is stored in the `pgdata` volume. Resetting it means `docker compose down -v`, which
  **deletes the database**.
- `docker-compose.yml` does not publish the `db` or `redis` ports to your machine, so
  `localhost:5432` and `localhost:6379` only work if you run Postgres and Redis yourself or add
  `ports:` entries. It also does not mount `CSV_DIR` or `MODEL_STORE` into the worker, so the
  nightly job in Compose needs those folders mounted first.

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
`docs/baseline.csv` and `docs/baseline.png` (AUC by week for the logistic regression, LightGBM and the
rule score, with the 0.68 week-1 and 0.79 week-8 targets). Current results are in
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
- **`ZoneInfo keys must be normalized relative paths` (API or tests):** `APP_TIMEZONE=` is blank
  in `.env`. Set a zone name or delete the line (section 4).
- **API answers `503 authentication is not configured`:** set `JWT_ISSUER`, `JWT_AUDIENCE` and
  one of `JWT_PUBLIC_KEY` / `JWT_JWKS_URL`.
- **API answers a bare `401`:** the token is expired or was signed by a different key, issuer or
  audience than the API is configured with. Mint a fresh one with the same `.env`.
- **Nightly job says `DATABASE_URL`/`CSV_DIR` is not set, or the worker `REDIS_URL`:** fill those
  in (section 4) and restart the worker.
