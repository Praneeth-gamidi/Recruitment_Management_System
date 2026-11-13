# FastAPI MVP

The FastAPI application serves the recruiter workspace and database-backed
business API while reusing the existing SQLAlchemy session, ORM models, and
workflow services. It does not create tables, seed demo records, or run
migrations at startup.

## Run

From the repository root with Python 3.12:

```powershell
.\.venv312\Scripts\python.exe main.py
```

The default address is `http://127.0.0.1:8000`.

- UI: `/ui/`
- Swagger: `/docs`
- Health: `/health`
- Database health: `/health/db` (`SELECT 1` only)

## API surface

Recruitment endpoints are registered under `/api/v1`:

- Dashboard summary: `GET /dashboard`
- Requisitions: `GET/POST /requisitions`, `GET/PUT /requisitions/{id}`
- Active hiring managers: `GET /hiring-managers`
- Candidates: `GET/POST /candidates`, `GET /candidates/{id}`
- Applications: `GET/POST /applications`, `GET /applications/{id}`
- Application transition: `POST /applications/{id}/transition`
- Requisition approval workflow: `/requisitions/{id}/submit-for-approval`,
  `/approvals`, and the requisition-approval decision routes
- Authentication: `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/me`
- Administrator staff provisioning: `GET/POST /users`, `GET /roles`
- Scoped CSV reports: `/reports/requisitions.csv` and
  `/reports/applications.csv`

Collection endpoints support `limit` and `offset`; candidates and requisitions
also support search. Application transitions use the existing lifecycle
service and preserve stage history. New requisitions are always drafts and
cannot be opened through the MVP API.

## Security and scope

Authentication and RBAC protect the current recruiter and approval routes.
Access is filtered by requisition scope where the workflow supports it. The
API rejects non-loopback clients and the default bind address is local-only.
This is only for trusted local evaluation; do not expose it through a public
proxy or network. Activation/reset email delivery, privileged MFA, and
production deployment are deferred.

Interview scheduling, scorecard entry, offer actions, role revocation, and
account activation are not exposed as complete end-to-end workflows yet. The
health and database-health routes retain their existing behavior. PostgreSQL
migration and concurrent refresh-token tests require a separately provisioned
test database; routine API tests use isolated SQLite fixtures.

## Tests

```powershell
.\.venv312\Scripts\python.exe -m pytest -q
```
