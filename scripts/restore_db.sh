#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
    echo "Usage: $0 backup-directory new-database environment-file compose-project" >&2
    exit 2
fi

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

backup_dir="$(cd -- "$1" && pwd)"
restore_db="$2"
env_file="$3"
project_name="$4"

if [[ ! "$restore_db" =~ ^appops_restore_[a-z0-9_]+$ || ${#restore_db} -gt 63 ]]; then
    echo "Use a database name starting with appops_restore_ and at most 63 characters." >&2
    exit 1
fi

test -f "$env_file"
test -s "$backup_dir/database.dump"
test -f "$backup_dir/SHA256SUMS"

compose=(
    docker compose
    --env-file "$env_file"
    --project-name "$project_name"
    -f compose.yaml
)

"${compose[@]}" config --quiet

(
    cd "$backup_dir"
    sha256sum --check SHA256SUMS
)

echo "Creating recovery database: $restore_db"
"${compose[@]}" exec -T db sh -c '
    exec createdb \
        --username="$POSTGRES_USER" \
        --maintenance-db="$POSTGRES_DB" \
        --template=template0 \
        --no-password \
        -- "$1"
' sh "$restore_db"

echo "Restoring the archive..."
"${compose[@]}" exec -T db sh -c '
    exec pg_restore \
        --username="$POSTGRES_USER" \
        --dbname="$1" \
        --no-owner \
        --no-acl \
        --single-transaction \
        --exit-on-error \
        --no-password
' sh "$restore_db" < "$backup_dir/database.dump"

echo "Archive restored into: $restore_db"
