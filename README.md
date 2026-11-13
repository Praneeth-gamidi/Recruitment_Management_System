# Recruitment Management System MVP

A database-backed recruiter workspace for managing requisitions, candidates,
application stages, and requisition approvals. Staff sign in through the
existing authentication/RBAC schema. The application does not generate demo
records or run database migrations on startup.

## Features

- Dashboard metrics for requisitions, candidates, applications, and application
  stages, with recent activity and useful empty states.
- Requisition listing, search, details, and editing while in `DRAFT` or
  `PENDING_APPROVAL`. New requisitions always start as `DRAFT`; the API does not
  provide a way to bypass approval and open one.
- Candidate creation, search by name/email, profile details, experience, and
  skills.
- A candidate-facing careers page for browsing open roles and submitting an
  application with privacy consent. Candidate applications do not create staff
  accounts or provide candidate sign-in.
- Application submission to an open requisition, application details, and
  stage transitions through the existing workflow service. Stage changes are
  recorded in `application_stage_history` and `audit_events`.
- Staff login, short-lived RS256 access tokens, rotating refresh tokens, and
  permission checks for the recruiter and approval APIs.
- Administrator-only staff account provisioning with explicit built-in role
  grants and optional existing HiringManager/Interviewer profile linkage.
- Requisition approval assignment, sequential approval decisions, revision
  return, and gated opening. Approval history and human actor identity are
  recorded without overwriting prior decisions.
- Scoped CSV exports for requisitions and applications, with spreadsheet
  formula-injection protection.
- FastAPI validation, pagination parameters, API error responses, and Swagger
  documentation.

The UI is plain HTML/CSS/JavaScript served by FastAPI (no frontend build
pipeline). An existing Streamlit launcher links to the same workspace.

## Architecture

- **API/UI:** FastAPI, Pydantic, static HTML/CSS/JavaScript.
- **Business/data layer:** SQLAlchemy 2.x and existing service-layer workflow
  checks.
- **Database:** PostgreSQL for configured application use; SQLite in isolated
  unit/API tests.
- **Migrations:** Alembic. Migrations are not run automatically.

The recruiter and authentication endpoints are under `/api/v1`. The system
health endpoints (`/health`, `/health/db`) remain unchanged.

## Project structure

```text
src/
  api/                 FastAPI app, v1 routes, static recruiter UI
  business_rules/      Application lifecycle rules
  core/                Settings, logging, and exception handlers
  database/            Existing SQLAlchemy engine/session
  models/              Recruitment and authentication/RBAC ORM models
  schemas/             API request/response validation
  services/            Existing business workflows and security services
tests/                 Unit, API, model, and isolated migration tests
migrations/            Alembic history (unchanged for this MVP)
dashboard/app.py       Streamlit launcher for the FastAPI workspace
```

## Prerequisites and setup

- Windows PowerShell
- Python 3.12
- PostgreSQL with the approved schema already applied if using the configured
  PostgreSQL database

Create and activate a virtual environment if `.venv312` does not already
exist:

```powershell
py -3.12 -m venv .venv312
.\.venv312\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The project environment is also directly usable without activation:

```powershell
.\.venv312\Scripts\python.exe -m pip install -r requirements.txt
```

## Environment configuration and database safety

The application loads database settings from `.env` (`DATABASE_URL`, or
`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`). JWT issuer,
audience, private-key path, and public-key path are supplied through
`JWT_ISSUER`, `JWT_AUDIENCE`, `JWT_PRIVATE_KEY_PATH`, and
`JWT_PUBLIC_KEY_PATH`. `.env.example` is a template only. Do not replace an
existing `.env` or commit its contents. The default example names
`recruitment_db`; verify the target and credentials privately before starting
the API.

To create a local configuration only when one does not already exist:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit the local file privately; do not paste credentials into source code,
terminal logs, or submissions.

### Fast local demo login (recommended)

There is no hardcoded administrator email or password. To get an administrator
login without touching PostgreSQL or `.env`, create a separate SQLite demo
database under your Windows user profile. This creates the existing ORM schema
in that new local file, seeds the approved built-in RBAC definitions, and
prompts you to choose the administrator password without echoing it. It does
not create demo candidates or requisitions. At the password prompt, type
normally and press Enter; the terminal intentionally displays no characters
or dots while you type.

Generate local JWT signing keys once (if they already exist, keep using them;
the generator intentionally refuses to overwrite them):

```powershell
.\.venv312\Scripts\python.exe scripts\generate_jwt_keys.py
```

In the same PowerShell window, set the JWT configuration and create your
administrator. Replace the sample email/name with your own. The recruiter
grant is limited to the department specified here (Engineering by default);
the ADMIN role provides global read access and the APPROVER grant enables
assigned approval decisions.

```powershell
$keys = Join-Path $env:LOCALAPPDATA 'RecruitmentManagementSystem\keys'
$env:JWT_ISSUER = 'http://127.0.0.1:8000'
$env:JWT_AUDIENCE = 'recruitment-local'
$env:JWT_PRIVATE_KEY_PATH = Join-Path $keys 'jwt-private.pem'
$env:JWT_PUBLIC_KEY_PATH = Join-Path $keys 'jwt-public.pem'
.\.venv312\Scripts\python.exe scripts\setup_local_demo.py --email "admin@example.invalid" --name "Demo Administrator" --recruiter-department Engineering
```

After setup succeeds, stop any already-running app with `Ctrl+C`. In that same
PowerShell window, explicitly select the newly created local SQLite database
and start the server. This avoids accidentally connecting the UI to the
database from `.env` or another terminal:

```powershell
$demoDb = Join-Path $env:LOCALAPPDATA 'RecruitmentManagementSystem\demo.sqlite3'
$env:DATABASE_URL = 'sqlite:///' + $demoDb.Replace('\', '/')
$keys = Join-Path $env:LOCALAPPDATA 'RecruitmentManagementSystem\keys'
$env:JWT_ISSUER = 'http://127.0.0.1:8000'
$env:JWT_AUDIENCE = 'recruitment-local'
$env:JWT_PRIVATE_KEY_PATH = Join-Path $keys 'jwt-private.pem'
$env:JWT_PUBLIC_KEY_PATH = Join-Path $keys 'jwt-public.pem'
.\.venv312\Scripts\python.exe main.py
```

Open <http://127.0.0.1:8000/ui/> and sign in with the email and password you
chose. The initial local demo database is empty, so create a hiring manager and
requisition in the UI. Requisitions still require approval before opening.
This setup never uses the configured `recruitment_db`, runs migrations, edits
`.env`, or overwrites an existing demo database. To rebuild after a successful
setup, manually back up or remove only the explicitly named local demo database
after stopping the app; the setup command will not overwrite it.

If sign-in displays **Internal server error**, stop the server with `Ctrl+C` and
rerun the commands above in one PowerShell window. `/health/db` only confirms
that a database connection can be opened; it does not prove that the server is
using the local demo database or that the authentication tables are present.
Do not retry credentials against a different or unverified database.

The application does not create tables or seed data at startup. The local demo
setup above creates tables only in its new SQLite demo file. Do not run
migrations against a database until you have verified its host and database
name and confirmed it is the intended target. If you explicitly intend to
migrate that target, first review the migration and take an appropriate
backup, then run:

```powershell
.\.venv312\Scripts\python.exe -m alembic upgrade head
```

No migrations are required for the MVP code changes in this submission.

Authentication requires the existing authentication/RBAC migration and
built-in role/permission seed data. Do not run migrations against the
configured database without confirming it is the intended target.

Generate a local RS256 key pair (the utility refuses to overwrite an existing
key pair):

```powershell
.\.venv312\Scripts\python.exe scripts\generate_jwt_keys.py
```

By default, the keys are stored under the current Windows user's
`%LOCALAPPDATA%\RecruitmentManagementSystem\keys` directory. Set the
environment variables for the current PowerShell session, using the paths
printed by the command:

```powershell
$env:JWT_ISSUER = "http://127.0.0.1:8000"
$env:JWT_AUDIENCE = "recruitment-local"
$env:JWT_PRIVATE_KEY_PATH = "<printed private key path>"
$env:JWT_PUBLIC_KEY_PATH = "<printed public key path>"
```

Create the first active administrator only after configuring and verifying a
separate intended database with the existing schema and built-in roles. The
bootstrap command prints the redacted target and requires typing its database
name; it refuses `recruitment_db`. It does not generate a password or assign
Recruiter/Approver roles unless explicitly requested:

```powershell
.\.venv312\Scripts\python.exe scripts\bootstrap_admin.py --email admin@example.invalid --name "Local Administrator" --recruiter-department Engineering
```

The command prompts for a password and confirmation. Use `--approver` only
when the account should also receive an Approver role. This is a local
bootstrap utility, not a public account-registration feature.

For isolated development or demos, configure `DATABASE_URL` to a separate
temporary database. Tests use in-memory SQLite and do not write to the
configured PostgreSQL database. The PostgreSQL migration/concurrency tests
require a separately provisioned database through
`AUTH_RBAC_TEST_DATABASE_URL`; without it, those tests are skipped.

## Run the application

From the project root:

```powershell
.\.venv312\Scripts\python.exe main.py
```

The default listener is `127.0.0.1:8000` (overridable with `APP_HOST` and
`APP_PORT`). Open:

- Recruiter workspace: <http://127.0.0.1:8000/ui/>
- Candidate careers page: <http://127.0.0.1:8000/careers>
- Swagger/OpenAPI: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/health>

The application is restricted to loopback clients and the default server
binds to `127.0.0.1`; this is suitable only for trusted local evaluation, not
deployment. Do not put it behind a public proxy or expose it to a network.
Production deployment is not supported: activation/reset email delivery and
privileged MFA are intentionally deferred.

The careers page is part of the loopback-only demo. It supports job browsing
and application submission, but not resume uploads, candidate accounts, or
application-status tracking.

The Streamlit launcher can be started separately after the API:

```powershell
.\.venv312\Scripts\python.exe -m streamlit run dashboard/app.py
```

## API overview

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/dashboard` | Live summary metrics, stage counts, recent records |
| GET/POST | `/api/v1/requisitions` | Search/list and create draft requisitions |
| GET/PUT | `/api/v1/requisitions/{id}` | View or update an editable requisition |
| GET | `/api/v1/requisitions/{id}/approvers` | List active, scoped approvers |
| POST | `/api/v1/requisitions/{id}/submit-for-approval` | Submit a draft with an ordered approval chain |
| GET | `/api/v1/requisitions/{id}/approvals` | View authorized approval history |
| POST | `/api/v1/requisition-approvals/{id}/decision` | Record an assigned approver's decision |
| POST | `/api/v1/requisitions/{id}/return-to-draft` | Return a rejected/revision-requested requisition |
| POST | `/api/v1/requisitions/{id}/open` | Open after approvals and compensation checks |
| GET | `/api/v1/approvals` | List the signed-in user's pending assigned approvals |
| GET | `/api/v1/reports/requisitions.csv` | Export authorized requisitions |
| GET | `/api/v1/reports/applications.csv` | Export authorized applications |
| GET | `/api/v1/hiring-managers` | Active managers for requisition forms |
| POST | `/api/v1/auth/login` | Authenticate a staff account |
| POST | `/api/v1/auth/refresh` | Rotate refresh token and issue an access token |
| POST | `/api/v1/auth/logout` | Revoke the signed-in refresh-token family |
| GET | `/api/v1/auth/me` | Read the signed-in account |
| GET | `/api/v1/roles` | List built-in roles (administrator only) |
| GET/POST | `/api/v1/users` | List or provision pending staff accounts |
| GET/POST | `/api/v1/candidates` | Search/list and create candidates with skills |
| GET | `/api/v1/candidates/{id}` | Candidate detail |
| GET/POST | `/api/v1/applications` | List/search and submit applications |
| GET | `/api/v1/applications/{id}` | Application details and stage history |
| POST | `/api/v1/applications/{id}/transition` | Validated stage/status transition |

List endpoints accept `limit` (maximum 200) and `offset`. Application
submission requires an `OPEN` requisition. Application lifecycle checks,
including offer and interview/scorecard gates, are enforced by the existing
service.

## Tests and checks

```powershell
.\.venv312\Scripts\python.exe -m pytest -q
.\.venv312\Scripts\python.exe -m compileall -q src scripts tests
```

Set `AUTH_RBAC_TEST_DATABASE_URL` only when using a dedicated isolated
PostgreSQL test database. Never point it at `recruitment_db`.

## Current limitations

- The recruiter and approval workflows require sign-in, but scope enforcement
  for all candidate/application and dashboard read paths is not yet complete.
  Keep the service loopback-only.
- Role revocation/changes and account activation are not available in the UI;
  provisioned staff accounts remain pending until activation delivery exists.
- Interview scheduling, scorecards, offer management, and richer analytics
  are not yet exposed as end-to-end workflows in the recruiter UI.
- Activation and password reset delivery, MFA, and production deployment are
  deferred.
- Candidate edits and bulk operations are not included.
- No synthetic/demo data is generated or inserted.
