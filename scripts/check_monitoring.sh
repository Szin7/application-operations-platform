#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

prometheus_image="prom/prometheus:v3.13.5"

if ! docker image inspect "$prometheus_image" >/dev/null 2>&1; then
    docker pull "$prometheus_image"
fi

promtool=(
    docker run --rm --pull never
    --network none
    --read-only
    --tmpfs /tmp
    --cap-drop ALL
    --security-opt no-new-privileges:true
    --mount "type=bind,src=$project_root/monitoring,dst=/etc/prometheus,readonly"
    --entrypoint /bin/promtool
    "$prometheus_image"
)

echo "Checking Prometheus configuration..."
"${promtool[@]}" check config /etc/prometheus/prometheus.yml

echo "Testing alert behavior..."
"${promtool[@]}" test rules /etc/prometheus/tests/api.test.yml

alertmanager_image="prom/alertmanager:v0.35.0"

if ! docker image inspect "$alertmanager_image" >/dev/null 2>&1; then
    docker pull "$alertmanager_image"
fi

echo "Checking Alertmanager configuration..."
docker run --rm --pull never \
    --network none \
    --read-only \
    --tmpfs /tmp \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --mount "type=bind,src=$project_root/monitoring/alertmanager.yml,dst=/etc/alertmanager/alertmanager.yml,readonly" \
    --entrypoint /bin/amtool \
    "$alertmanager_image" \
    check-config /etc/alertmanager/alertmanager.yml

echo "Monitoring checks passed."
