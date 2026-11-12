# Deployment and application rollback

Staging and production run locally as separate Docker Compose projects.

| Environment | API address | Database | Database host port |
| --- | --- | --- | --- |
| Staging | http://127.0.0.1:8002 | appops_staging | 55434 |
| Production | http://127.0.0.1:8003 | appops_production | 55435 |

Each environment has its own database volume and application account.

## Environment configuration

Use the templates in `deploy/` to prepare `.env.staging` and `.env.production`.
Set separate administrator and application passwords for each environment.
Existing database credentials must be preserved.

The private environment files are excluded from Git and Docker builds.

The scripts require Docker Compose, Bash, and uv. Install the project's
locked dependencies with `uv sync --locked`.

## Build a release

Commit the source changes first. Confirm that `git status --short` is empty.

```bash
release_commit="$(git rev-parse HEAD)"
release_image="application-operations-platform:$(git rev-parse --short=12 HEAD)"

docker build \
  --label "org.opencontainers.image.revision=$release_commit" \
  --tag "$release_image" \
  .
```

Record the built image ID:

```bash
docker image inspect --format '{{.Id}}' "$release_image"
```

Keep previously verified release images available for rollback.

## Deploy to staging

```bash
./scripts/deploy.sh staging "$release_image"
```

Check readiness, the expected version, and the affected API behaviour before
promoting the release:

```bash
curl --fail-with-body -sS http://127.0.0.1:8002/health/ready
curl --fail-with-body -sS http://127.0.0.1:8002/version
```

## Promote to production

Before updating an existing production database, take a backup:

```bash
./scripts/backup_db.sh .env.production application-operations-production
```

Deploy the same release image:

```bash
./scripts/deploy.sh production "$release_image"
```

The script requires the requested image to be running healthy in staging.
It prepares database access, applies migrations, starts the API, and checks
the running image ID. It saves APP_IMAGE after successful verification.

Deployment failures stop the script. Recovery is a manual operation.

## Roll back the application

Select a previously verified release. For the recorded exercise:

```bash
./scripts/rollback.sh production application-operations-platform:703d57ab27f4
```

The script compares the target image's Alembic head with the database's
recorded migration revision. Different revisions block the rollback.

It switches only the API service, waits for readiness, checks the image ID,
and saves the selected release in the environment file.

Afterward, verify the expected version and compare application records
with their saved values.

This procedure does not downgrade the database or restore a backup.
Matching revision numbers are a guard, not a complete compatibility test.
Review code and data changes before selecting a rollback target.

## Verified exercise: 12 November 2026

| Check | Observed result |
| --- | --- |
| Deploy with staging stopped | Production deployment blocked; production was not restarted |
| Promote an image absent from staging | Production deployment blocked; production was not restarted |
| Promote version 0.1.1 | Staging and production used the same image ID |
| Read the original production ticket after upgrade | Every field matched the saved record |
| Roll production back to version 0.1.0 | Original image ID restored; API healthy |
| Read the original ticket after rollback | Every field still matched |
| Check staging after production rollback | Staging remained on version 0.1.1 |
| Check saved production configuration | APP_IMAGE selected the original release |

Original release: `application-operations-platform:703d57ab27f4`

Original image ID:
`sha256:c81727d82f36466d922d05ad0e1eee8235bc14edec9bcfcee29e624fbe6ed64a`

Candidate release: `application-operations-platform:98e8c9050371`

Candidate image ID:
`sha256:522c6a6ecc8c86749a1f307d6ef29d7d88d0869c97d5175baf5ddc987eae8e2c`

Both releases used migration revision `0001`. The application change was
a version bump from `0.1.0` to `0.1.1`.

The original ticket and image details were saved locally in
`backups/rollback-check.json`. A production backup was created at
`backups/20261112T170840Z-seo7SR`.

The exercise verified application rollback with an unchanged schema and
one demonstration ticket. It did not test rollback across schema changes.

These environments share one laptop. This is a local deployment exercise,
not a highly available production installation.
