#!/usr/bin/env bash
set -euo pipefail

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
    -f compose.tools.yaml
)

echo "Checking configuration..."
"${compose[@]}" config --quiet

echo "Building the application image..."
"${compose[@]}" build api

echo "Starting PostgreSQL..."
"${compose[@]}" up -d --wait --wait-timeout 120 db

echo "Preparing the database role and schema..."
"${compose[@]}" run --rm --no-deps -T setup \
    python scripts/bootstrap_db.py

echo "Applying database migrations..."
"${compose[@]}" run --rm --no-deps -T setup \
    alembic upgrade head

echo "Starting the API..."
"${compose[@]}" up -d --no-build --wait --wait-timeout 120 api

"${compose[@]}" ps
echo "Local environment is ready."
