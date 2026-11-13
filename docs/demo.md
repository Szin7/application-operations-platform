# Check the running lab

Run from the repository root in WSL after staging, production, both Nginx
proxies, and monitoring are running. These commands inspect the services;
they do not deploy a release or introduce an outage.

For a fresh checkout, start with [Local setup](setup.md). Recorded results
are in the [build record](evidence.md).

## Containers and readiness

```bash
docker ps --filter name=application-operations-staging- \
  --filter name=application-operations-production- \
  --filter name=application-operations-proxy- \
  --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'

for port in 8002 8003 8082 8083; do
  printf '\nPort %s readiness:\n' "$port"
  curl --fail --silent --show-error "http://127.0.0.1:$port/health/ready"
  printf '\nVersion:\n'
  curl --fail --silent --show-error "http://127.0.0.1:$port/version"
  printf '\n'
done
```

Each readiness request should return `{"status":"ready"}`. Ports 8082 and
8083 go through Nginx; 8002 and 8003 go directly to the APIs. The version
response reports the application version, not the container's image digest.

## CI and deployment records

With GitHub CLI signed in:

```bash
for run_id in 43427425933 43344606433 43347528825; do
  gh run view "$run_id" --repo Szin7/application-operations-platform \
    --json url,conclusion --jq '"\(.conclusion)  \(.url)"'
done
```

These are the final recovery-integration CI run and the earlier staging and
production deployment runs. CI publishing did not redeploy the lab. The
recorded deployments used release `a56088c1b7bb`, version `0.1.2`.

The [build record](evidence.md#delivery-checks) also links the deliberately
rejected promotion. Deployment jobs are gated off in the public repository;
view the existing runs instead of dispatching them as a service check.

## Grafana

Open <http://localhost:3000> and sign in with the local Grafana account.

- **Application Operations** shows API traffic, status codes, and response times.
- **Infrastructure and Readiness** shows the four readiness routes, three
  exporters, WSL resources, and container CPU and memory.

The environment selector on the infrastructure dashboard filters readiness
panels. Host metrics belong to the shared WSL machine. `/` reports the WSL
virtual filesystem; `/mnt/d` reports the Windows D: volume.

If the earlier outage has aged out of the dashboard, use the
[recorded screenshots](evidence.md#infrastructure-dashboard-screenshots).
A missing sample is not a measured zero. See the
[panel guide](runbooks/infrastructure-dashboard.md#read-the-panels) for units
and the meaning of each graph.

## Saved recovery result

On the original lab checkout, read the result from the completed staging drill:

```bash
python3 - <<'PYTHON'
import json
from pathlib import Path

path = Path("backups/staging-recovery-20261113T123703731666Z/evidence.json")
record = json.loads(path.read_text())
print("Staging recovery:", record["status"])
print("Saved release:", record["saved_release"])
PYTHON
```

That file is local and is absent from a fresh clone. Reading it does not rerun
the drill. The [recovery runbook](runbooks/staging-recovery.md) contains the
procedure and a summary of the result.

Keep credentials, database archives, and raw ticket data out of screenshots.
For the boundaries of this setup, see [Scope and limitations](limitations.md).
