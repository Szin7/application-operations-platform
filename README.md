# Application Operations Platform

A small service-ticket API for practising application deployment and database operations.

The application uses FastAPI and PostgreSQL. Docker Compose runs the services, Alembic tracks database changes, and a startup script handles database preparation and migrations.

## Current features

- Create and retrieve tickets.
- List tickets with status filtering and pagination.
- Change ticket status to open, in progress, or resolved.
- Check application liveness and database readiness.
- Run database setup repeatedly without removing existing tickets.
- Run unit tests and PostgreSQL integration tests.

## Requirements

To run the containers:

- Docker with Docker Compose
- Bash, available in Linux or WSL
- Available host ports 8001 and 55432

To run tests locally:

- Python 3.14
- uv
- Available host port 55433 for the test database

On Windows, run the commands below inside WSL with Docker Desktop integration enabled.

## First-time setup

Run these commands from the repository root.

Create a local configuration file:

```bash
cp -n .env.example .env
chmod 600 .env
nano .env
```

Set separate, nonempty values for:

- `POSTGRES_PASSWORD`: database administrator password
- `APP_DB_PASSWORD`: application account password

Keep the other development settings from the example. Do not commit `.env`.

If `.env` already exists, use its existing credentials. Editing a password in the file does not change an existing database account's password.

Start the application:

```bash
./scripts/start_local.sh
```

The script:

1. Checks the Compose configuration.
2. Builds the application image.
3. Starts PostgreSQL and waits for its health check.
4. Creates the application role and schema if needed, then applies permissions.
5. Applies pending database migrations.
6. Starts the API and waits for readiness.

API documentation: http://localhost:8001/docs

Check readiness:

```bash
curl -i http://localhost:8001/health/ready
```

## API endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Service name |
| GET | `/version` | Application version |
| GET | `/health/live` | Application responsiveness |
| GET | `/health/ready` | Database connection and query |
| GET | `/metrics` | Request counts and timings for Prometheus |
| POST | `/tickets` | Create a ticket |
| GET | `/tickets` | List tickets |
| GET | `/tickets/{ticket_id}` | Retrieve a ticket |
| PATCH | `/tickets/{ticket_id}/status` | Change ticket status |

Example request:

```bash
curl -i -X POST http://localhost:8001/tickets \
  -H 'Content-Type: application/json' \
  -d '{"title":"Check slow responses","priority":"high"}'
```

Use the returned ID when retrieving or updating the ticket.

Priorities: `low`, `medium`, `high`, `critical`.

Statuses: `open`, `in_progress`, `resolved`. Transitions between these statuses are currently unrestricted.

Listing supports `status`, `limit`, and `offset`. Results are ordered newest first, with ID as the tie-breaker. The default page size is 20; the maximum is 100.

## Database access

The API connects using a restricted application account. It can read and write ticket data but cannot create tables in the application schema.

A separate setup container receives administrator credentials for bootstrap and migrations. The API container receives only its application database settings.

PostgreSQL data is stored in a named Docker volume.

## Tests

Install the locked dependencies, including development tools:

```bash
uv sync --locked
```

Run the default suite:

```bash
uv run python -m pytest -v
```

The two database integration tests are skipped unless explicitly enabled.

### Prepare the test database

Create a separate configuration file:

```bash
cp -n .env.example .env.test
chmod 600 .env.test
nano .env.test
```

Use these settings, plus separate passwords for both test accounts:

| Variable | Test value |
| --- | --- |
| POSTGRES_DB | appops_test |
| POSTGRES_USER | postgres |
| POSTGRES_PORT | 55433 |
| APP_DB_HOST | 127.0.0.1 |
| APP_DB_PORT | 55433 |
| APP_DB_NAME | appops_test |
| APP_DB_USER | appops_test_app |

Start and prepare the test database:

```bash
docker compose --env-file .env.test -p application-operations-test up -d --wait --wait-timeout 120 db
uv run --env-file .env.test python scripts/bootstrap_db.py
uv run --env-file .env.test alembic upgrade head
```

Run all tests:

```bash
RUN_DB_TESTS=1 uv run --env-file .env.test python -m pytest -v
```

The integration tests verify the database name and account before running. They require an empty test ticket table and remove only the rows they create.

The current suite has 52 tests. The integration tests cover persisted changes, filtering, ordering, and pagination.

Check Python code:

```bash
uv run ruff check app tests migrations scripts
uv run ruff format --check app tests migrations scripts
```

## Daily commands

Start or update the local environment:

```bash
./scripts/start_local.sh
```

Check services and recent API logs:

```bash
docker compose ps
docker compose logs --tail=50 api
```

Stop the development services while keeping their data:

```bash
docker compose stop
```

Stop the test database:

```bash
docker compose --env-file .env.test -p application-operations-test stop db
```

## Runtime settings

The API image runs as user 10001. Compose gives it a read-only root filesystem, writable temporary storage, and no Linux capabilities.

Local environment files and development tools are excluded from the application image.

The API connects to `db:5432` inside the Compose network. Host-side database tools use `127.0.0.1:55432`.

## Continuous integration

GitHub Actions runs on pushes to `main`, pull requests, and manual requests.

The workflow uses Python 3.14, locked dependencies, and a fresh PostgreSQL
test database. It prepares the application account and applies migrations
before running the database tests.

| Check | First verified result |
| --- | --- |
| Python linting and formatting | Passed |
| Shell script syntax | Passed |
| Unit test step | 33 passed; 2 integration tests intentionally skipped |
| PostgreSQL integration step | 2 passed |
| Docker image build | Passed |
| Image checks | UID 10001; local environment files, pytest, and Ruff absent; version matched project metadata |

All 35 tests ran across the two test steps.

[First successful CI run](https://github.com/Szin7/application-operations-platform/actions/runs/43276857853)
verified commit `26f90315c1593f92fd6eb5704434090437895fb2` on
12 November 2026.

After checks pass on `main`, the workflow publishes the tested image to
GitHub Container Registry. Pull requests run checks without publishing.
Staging and production deployments are started manually.

See [Registry releases](docs/runbooks/registry-releases.md) for release
commands and the first verified deployment from GHCR.

## Monitoring

Prometheus collects metrics from staging and production. A provisioned
Grafana dashboard shows scrape status, request traffic, server errors,
and response times, with an environment selector.

Alertmanager forwards firing and recovery notifications to a local
receiver. A staging outage check verified both messages.

See the [monitoring runbook](docs/runbooks/monitoring.md) for setup,
dashboard details, notification delivery, and troubleshooting.

## Deployments and rollback

Staging deployment and production promotion can be started manually through GitHub Actions. See [Deploy through GitHub Actions](docs/runbooks/actions-deployments.md) for the commands and verified runs.

See [Deployment and application rollback](docs/runbooks/deployment-rollback.md) for release commands and verified results.

## Backup and restore

See [Database backup and restore](docs/runbooks/backup-restore.md) for the procedure and verified results.

## Project status

Local deployment, database migrations, health checks, automated tests, and database backup and restore have been verified.

Authentication is not implemented. The API is currently published on the local loopback address.

Staging-to-production promotion and application rollback have been verified.

CI checks, image publishing, and manual promotion of a registry image
through staging and production have been verified.

Prometheus collection and the Grafana dashboard have been verified for staging and production.

A staging outage check confirmed that the scrape alert fires and clears after recovery.

Local webhook notification delivery has been verified.

Manual deployment through GitHub Actions has been verified for staging and production. Notifications currently stay on the local machine.
