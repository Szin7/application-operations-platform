# Nginx reverse proxy

Each environment has its own Nginx container in `compose.proxy.yaml`.
The proxy joins that environment's existing Docker network and forwards
requests to its API. The API images and database configuration are unchanged.

| Environment | Proxy address | Direct API address | Docker upstream |
| --- | --- | --- | --- |
| Staging | http://127.0.0.1:8082 | http://127.0.0.1:8002 | `application-operations-staging-api-1:8000` |
| Production | http://127.0.0.1:8083 | http://127.0.0.1:8003 | `application-operations-production-api-1:8000` |

Both proxy ports bind to loopback. Direct API ports remain available for
troubleshooting; requests sent directly to the API bypass Nginx's limits.
This is local HTTP access without TLS or authentication.

## Before starting

Run commands from the repository root in WSL. Prepare staging and production
using the [deployment runbook](deployment-rollback.md) first. Both API and
database pairs must be healthy, and ports 8082 and 8083 must be available.
The proxy does not create the external application networks.

The image is Nginx 1.30.6, Alpine slim, pinned in Compose to:

```text
nginx/nginx-unprivileged@sha256:931bec1e41a3a643f2672162405093fe04002dd20e41d04faf67d700b7556b49
```

Validate both configurations:

```bash
./scripts/check_proxy.sh
```

This checks Compose and runs `nginx -t` in temporary containers with no
network access. It downloads the pinned image if missing. It does not
start the proxies, create application networks, or test upstream routing.
The same check runs in CI; live routing checks run separately in the lab.

## Start staging, then production

Start and check staging before starting production:

```bash
docker compose -f compose.proxy.yaml up -d --no-deps --no-build \
  --pull never --wait --wait-timeout 90 staging
curl --fail --silent --show-error http://127.0.0.1:8082/health/ready
curl --fail --silent --show-error http://127.0.0.1:8082/version
```

After staging passes:

```bash
docker compose -f compose.proxy.yaml up -d --no-deps --no-build \
  --pull never --wait --wait-timeout 90 production
curl --fail --silent --show-error http://127.0.0.1:8083/health/ready
curl --fail --silent --show-error http://127.0.0.1:8083/version
docker compose -f compose.proxy.yaml ps
```

Each health check requests `/health/ready` through Nginx to the API, so
it depends on database readiness as well as the proxy. An unhealthy status
does not itself trigger a Docker restart; `unless-stopped` handles process
exits and daemon restarts according to Docker's restart policy.

## Runtime settings

Both proxies run as UID/GID 101 with a read-only root filesystem, all Linux
capabilities dropped, and `no-new-privileges`. Each has a writable 16 MiB
temporary filesystem, a 64 MiB memory limit, a 0.25 CPU limit, and a 64-PID
limit. Configuration mounts are read-only. Docker logs rotate at 10 MB per
file with three files retained per container.

Nginx limits request bodies to 64 KiB and uses bounded connection and
request timeouts. It preserves paths and query parameters and passes
application errors through. Automatic upstream retries are disabled.
The server header omits the Nginx version.

The configurations use Docker DNS at `127.0.0.11`, a five-second resolver
cache, and a variable upstream address to allow DNS refresh after API
container replacement. The initial checks below did not exercise container
replacement or establish zero-downtime deployment.

Nginx sets forwarded headers, but this integration does not change Uvicorn's
trusted proxy settings or claim verified original-client IP reporting.
Prometheus continues scraping the APIs directly; a healthy API scrape alone
does not prove that the proxy is reachable.

## Inspect or change a proxy

```bash
docker compose -f compose.proxy.yaml ps
docker compose -f compose.proxy.yaml logs --tail=50 staging production
```

For a 502 response, compare the direct API readiness with proxy readiness,
then inspect the proxy log, upstream container name, and Docker network.
A 413 response means the request exceeded the proxy body-size limit.
Application validation errors such as 422 should pass through unchanged.

After editing a configuration, run `./scripts/check_proxy.sh`, then recreate
only the affected proxy. For example, for staging:

```bash
docker compose -f compose.proxy.yaml up -d --no-deps --force-recreate \
  --no-build --pull never --wait --wait-timeout 90 staging
curl --fail --silent --show-error http://127.0.0.1:8082/health/ready
```

Recreating a proxy briefly interrupts access through that proxy. To undo a
configuration change, restore its previously verified configuration, validate
it, and recreate that proxy again. The application rollback procedure remains
separate. To stop both proxies while keeping application services running:

```bash
docker compose -f compose.proxy.yaml stop
```

## Verified integration — 13 November 2026

The sequence was image verification, staging startup and routing checks,
production startup and routing checks, then runtime checks for both proxies.
This followed the earlier deployment, promotion-rejection, backup-recovery,
and monitoring exercises. Application release `a56088c1b7bb` remained in use.

| Check | Recorded result |
| --- | --- |
| Image | Nginx 1.30.6; UID 101; pinned digest verified |
| Configuration and startup | Both `nginx -t` checks passed; both proxies healthy |
| Routing | Direct and proxied response bodies matched for liveness, readiness, version, ticket listing, filtering, pagination, OpenAPI, and docs |
| Application errors | Invalid limit returned matching 422; unknown route returned matching 404 |
| Body-size limit | Both proxies rejected a 70 KiB invalid JSON body with 413 |
| Runtime | Non-root user, read-only root/config mount, dropped capabilities, privilege restriction, resource limits, log rotation, restart policy, loopback bindings, and separate networks checked |
| Existing services | Staging and production API/database IDs, images, start times, and healthy states unchanged across proxy startup; staging proxy unchanged across production proxy startup |

Runtime, request-size, and readiness evidence was saved locally at
`backups/proxy-check-20261113T042015231868Z.json`.
Its timestamp is UTC; the record includes the checked configuration hashes
and container IDs. It does not contain the earlier routing comparisons or
before/after startup snapshots. Those results were reviewed from terminal
output. The raw record is excluded from Git with other local evidence.

These checks did not cover successful ticket writes through the proxy,
API replacement, backend outages, concurrency, or load. Nginx configuration
validation in CI is distinct from these recorded live checks.
