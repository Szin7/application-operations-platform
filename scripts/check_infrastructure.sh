#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

echo "Checking infrastructure Compose configuration..."
docker compose -f compose.infrastructure.yaml config --quiet

echo "Building Node Exporter and running its WSL mount regression tests..."
image="application-operations-node-exporter:1.12.1-wsl.1"
docker build --tag "$image" deploy/node-exporter

test "$(docker image inspect --format '{{.Config.User}}' "$image")" = "65534:65534"
version="$(docker run --rm --pull never --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --pids-limit 64 --memory 64m --cpus 0.25 \
  "$image" --version 2>&1)"
printf '%s\n' "$version"
[[ "$version" == *"version 1.12.1-wsl.1"* ]]

echo "Infrastructure configuration and image checks passed. No lab services were started or restarted."
