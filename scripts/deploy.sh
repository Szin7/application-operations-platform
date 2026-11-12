#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 staging|production application-operations-platform:commit" >&2
    exit 2
fi

case "$1" in
    staging|production) environment="$1" ;;
    *) echo "Environment must be staging or production." >&2; exit 2 ;;
esac

image="$2"
if [[ ! "$image" =~ ^application-operations-platform:[0-9a-f]{12}$ ]]; then
    echo "Use a release image tagged with the 12-character Git commit." >&2
    exit 2
fi

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

env_file=".env.$environment"
project_name="application-operations-$environment"
test -f "$env_file"
command -v uv >/dev/null

image_id="$(docker image inspect --format '{{.Id}}' "$image")"
revision="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")"

if [[ ! "$revision" =~ ^[0-9a-f]{40}$ || "${revision:0:12}" != "${image##*:}" ]]; then
    echo "Image source label does not match its release tag." >&2
    exit 1
fi

export APP_IMAGE="$image"
compose=(
    docker compose --env-file "$env_file"
    --project-name "$project_name"
    -f compose.yaml -f compose.tools.yaml
)
"${compose[@]}" config --quiet

if [[ "$environment" == "production" ]]; then
    staging_container="$(docker compose --env-file .env.staging \
        --project-name application-operations-staging \
        -f compose.yaml -f compose.tools.yaml ps -q api)"

    if [[ -z "$staging_container" ]]; then
        echo "Start and verify this release in staging first." >&2
        exit 1
    fi

    staging_image="$(docker inspect --format '{{.Image}}' "$staging_container")"
    staging_health="$(docker inspect --format '{{.State.Running}} {{.State.Health.Status}}' "$staging_container")"

    if [[ "$staging_image" != "$image_id" || "$staging_health" != "true healthy" ]]; then
        echo "Production requires the same image running healthy in staging." >&2
        exit 1
    fi
fi

echo "Deploying $image to $environment..."
"${compose[@]}" up -d --no-build --pull never --wait --wait-timeout 120 db
"${compose[@]}" run --rm --no-deps --pull never -T setup python scripts/bootstrap_db.py
"${compose[@]}" run --rm --no-deps --pull never -T setup alembic upgrade head
"${compose[@]}" up -d --no-build --pull never --wait --wait-timeout 120 api

container="$("${compose[@]}" ps -q api)"
running_id="$(docker inspect --format '{{.Image}}' "$container")"
if [[ "$running_id" != "$image_id" ]]; then
    echo "Running image does not match the requested release." >&2
    exit 1
fi

uv run --locked python - "$env_file" "$image" <<'PY'
import sys
from pathlib import Path

from dotenv import set_key

path = Path(sys.argv[1])
set_key(str(path), "APP_IMAGE", sys.argv[2])
path.chmod(0o600)
PY

"${compose[@]}" ps
printf 'Deployment verified: %s\nImage ID: %s\n' "$environment" "$image_id"
