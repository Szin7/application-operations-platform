# Database backup and restore

## Create a backup

From the repository root, with the development database running:

```bash
./scripts/backup_db.sh
```

The script creates a new directory under `backups/` containing:

- `database.dump`: PostgreSQL custom-format archive
- `archive.list`: archive contents
- `SHA256SUMS`: checksum for the dump
- `source-project.txt`: source Compose project

Existing backups are preserved. Failed dumps remain marked `.partial`.

Backups are excluded from Git and Docker build contexts.

## Restore into a separate database

The test PostgreSQL container must be running:

```bash
docker compose --env-file .env.test -p application-operations-test up -d --wait --wait-timeout 120 db
```

Select the backup directory printed by the backup script:

```bash
read -r -p "Backup directory: " backup_dir
recovery_db="appops_restore_$(date -u +%Y%m%d%H%M%S)"
```

Restore it:

```bash
./scripts/restore_db.sh \
  "$backup_dir" \
  "$recovery_db" \
  .env.test \
  application-operations-test
```

The script checks the checksum and creates a new database from `template0`.
It stops if the database already exists. Restoration runs in one transaction.

Ownership and access grants are not restored from the archive. Apply the application permissions separately:

```bash
APP_DB_NAME="$recovery_db" POSTGRES_DB="$recovery_db" \
  uv run --env-file .env.test python scripts/bootstrap_db.py
```

Keep using the same terminal so `recovery_db` remains available.

## Check the recovered database

Inspect the migration record and ticket count:

```bash
docker compose --env-file .env.test -p application-operations-test exec -T db \
  psql -U postgres -d "$recovery_db" \
  -c "SELECT version_num FROM public.alembic_version; SELECT count(*) FROM app.tickets;"
```

Compare the recovered records with what was present when the backup was taken.
Also check application access using the restricted account before treating recovery as complete.

## Verified recovery

On 12 November 2026:

- Restored backup `20261112T131134Z-w2BcMi`.
- Created recovery database `appops_restore_20261112131346`.
- Confirmed migration version `0001`.
- Confirmed one recovered ticket.
- Verified every returned field of ticket 1 against its original values.
- Received HTTP 200 from readiness and ticket retrieval through FastAPI TestClient.
- Confirmed the development API still returned the original ticket.

The check covered the current application schema and one demonstration ticket.

## Current limits

Backups remain on the same laptop. Off-machine storage and scheduled backups are not configured.

The dump does not back up cluster roles or their passwords. Keep credentials separately and use the bootstrap script to prepare application access.

This procedure restores into a separate database. Switching the running API to that database is a separate operation.
