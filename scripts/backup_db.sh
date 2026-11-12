#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# -ne 0 && $# -ne 2 ]]; then
    echo "Usage: $0 [environment-file compose-project]" >&2
    exit 2
fi

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

env_file="${1:-.env}"
project_name="${2:-application-operations-dev}"

if [[ ! -f "$env_file" ]]; then
    echo "Environment file not found: $env_file" >&2
    exit 1
fi

compose=(
    docker compose
    --env-file "$env_file"
    --project-name "$project_name"
    -f compose.yaml
)

"${compose[@]}" config --quiet

mkdir -p backups
backup_dir="$(mktemp -d "$project_root/backups/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"

echo "Creating database backup..."
"${compose[@]}" exec -T db sh -c '
    exec pg_dump \
        --username="$POSTGRES_USER" \
        --dbname="$POSTGRES_DB" \
        --format=custom \
        --no-acl \
        --no-password
' > "$backup_dir/database.dump.partial"

test -s "$backup_dir/database.dump.partial"

echo "Checking the archive listing..."
"${compose[@]}" exec -T db pg_restore --list \
    < "$backup_dir/database.dump.partial" \
    > "$backup_dir/archive.list"

mv "$backup_dir/database.dump.partial" "$backup_dir/database.dump"

(
    cd "$backup_dir"
    sha256sum database.dump > SHA256SUMS
    sha256sum --check SHA256SUMS
)

printf '%s\n' "$project_name" > "$backup_dir/source-project.txt"

echo "Backup saved: $backup_dir"
ls -lh "$backup_dir/database.dump"
