#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

echo "Checking proxy Compose configuration..."
image="$(docker compose -f compose.proxy.yaml config --format json | python3 -c '
import json
import sys

services = json.load(sys.stdin)["services"]
assert set(services) == {"staging", "production"}, "Expected both proxy services"
images = {service["image"] for service in services.values()}
assert len(images) == 1, "Both proxies must use the same image"
image = images.pop()
assert "@sha256:" in image, "Pin the proxy image by digest"
print(image)
')"

if ! docker image inspect "$image" >/dev/null 2>&1; then
    docker pull "$image"
fi

for environment in staging production; do
    echo "Checking $environment Nginx configuration..."
    docker run --rm --pull never \
        --network none \
        --user 101:101 \
        --read-only \
        --tmpfs /tmp:rw,noexec,nosuid,size=16m,mode=1777 \
        --cap-drop ALL \
        --security-opt no-new-privileges:true \
        --memory 64m \
        --cpus 0.25 \
        --pids-limit 64 \
        --mount "type=bind,src=$project_root/deploy/nginx/$environment.conf,dst=/etc/nginx/nginx.conf,readonly" \
        --entrypoint nginx \
        "$image" -t
done

echo "Proxy configuration checks passed."
