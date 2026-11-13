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
"${promtool[@]}" test rules /etc/prometheus/tests/infrastructure.test.yml

echo "Checking infrastructure dashboard queries..."
uv run --locked python scripts/check_infrastructure_dashboard.py --emit-rules |
    docker run --rm -i --pull never \
        --network none \
        --read-only \
        --cap-drop ALL \
        --security-opt no-new-privileges:true \
        --entrypoint /bin/promtool \
        "$prometheus_image" check rules /dev/stdin

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

blackbox_image="quay.io/prometheus/blackbox-exporter@sha256:ea1c7aa3ef3f307cd03e85f34abb604478ccb90b567fc690da0cd9776da76b13"
if ! docker image inspect "$blackbox_image" >/dev/null 2>&1; then
    docker pull "$blackbox_image"
fi

echo "Checking readiness probe configuration..."
docker run --rm --pull never \
    --network none \
    --read-only \
    --user 65534:65534 \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --mount "type=bind,src=$project_root/monitoring/blackbox.yml,dst=/etc/blackbox_exporter/config.yml,readonly" \
    "$blackbox_image" \
    --config.file=/etc/blackbox_exporter/config.yml \
    --config.check

echo "Monitoring checks passed."
