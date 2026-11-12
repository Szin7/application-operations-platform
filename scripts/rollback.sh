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
test -f "$env_file"
command -v uv >/dev/null

image_id="$(docker image inspect --format '{{.Id}}' "$image")"
export APP_IMAGE="$image"

compose=(
    docker compose --env-file "$env_file"
    --project-name "application-operations-$environment"
    -f compose.yaml -f compose.tools.yaml
)
"${compose[@]}" config --quiet

target_revision="$(docker run --rm --pull never --network none --read-only \
    "$image_id" python -c '
from alembic.config import Config
from alembic.script import ScriptDirectory

revision = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
if revision is None:
    raise SystemExit("Target image has no migration revision")
print(revision)
')"

database_revision="$("${compose[@]}" exec -T db sh -c '
    exec psql -X --no-password --tuples-only --no-align \
        --set=ON_ERROR_STOP=1 \
        --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" \
        --command="SELECT version_num FROM public.alembic_version"
')"

if [[ "$target_revision" != "$database_revision" ]]; then
    printf 'Rollback blocked: image migration %s, database migration %s\n' \
        "$target_revision" "$database_revision" >&2
    exit 1
fi

printf 'Migration revision matched: %s\n' "$database_revision"
echo "Switching $environment API to $image..."
APP_IMAGE="$image_id" "${compose[@]}" up -d --no-deps --no-build \
    --pull never --wait --wait-timeout 120 api

container="$("${compose[@]}" ps -q api)"
test "$(docker inspect --format '{{.Image}}' "$container")" = "$image_id"

uv run --locked python - "$env_file" "$image" <<'PY'
import sys
from pathlib import Path

from dotenv import set_key

path = Path(sys.argv[1])
set_key(str(path), "APP_IMAGE", sys.argv[2])
path.chmod(0o600)
PY

printf 'API rollback completed: %s\nImage ID: %s\n' "$environment" "$image_id"
