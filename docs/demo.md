# Five-minute project demo

Run from the repository root in WSL with Docker, staging, production,
and monitoring already running. GitHub CLI must be signed in.
These commands only inspect services and evidence. They are intended for
the existing lab checkout; its local evidence files are not included in Git.
For a GitHub-only review, use the [evidence walkthrough](evidence.md).

CI remains enabled in the public repository. The Actions deployment and
runner-check jobs are gated off by their private-repository condition.
Use the historical runs below to demonstrate the verified private-lab
deployments; do not dispatch new deployment runs for this demo.

## 1. Explain the setup — 30 seconds

Show the README architecture diagram. Explain that the small ticket API
is used to practise deployments, database permissions, monitoring,
rollback, and recovery. Both environments run on one laptop.

## 2. Show the services — 60 seconds

```bash
docker ps --filter name=application-operations-staging- \
  --filter name=application-operations-production- \
  --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'

for port in 8002 8003; do
  printf '\nPort %s readiness:\n' "$port"
  curl --fail --silent --show-error "http://127.0.0.1:$port/health/ready"
  printf '\nVersion:\n'
  curl --fail --silent --show-error "http://127.0.0.1:$port/version"
  printf '\n'
done
```

Readiness checks database access. The version endpoint shows the
application version; the deployment workflow also checks the image.

## 3. Show delivery evidence — 60 seconds

```bash
for run_id in 43302633612 43344606433 43347528825; do
  gh run view "$run_id" --repo Szin7/application-operations-platform \
    --json url,conclusion --jq '"\(.conclusion)  \(.url)"'
done
```

These historical runs show CI, staging deployment, and production
promotion for release `a56088c1b7bb`, application version `0.1.2`.
Open the production run to show backup and verification steps.
Later CI runs do not automatically replace the running release.

## 4. Show rejection and recovery — 60 seconds

```bash
gh run view 43351535975 --repo Szin7/application-operations-platform \
  --json url,conclusion --jq '"\(.conclusion)  \(.url)"'

python3 - <<'DEMO_EVIDENCE'
import json
from pathlib import Path

records = (
    ("Promotion guard", "backups/production-guard-20261113T022057Z-cbf9a69e-result.json"),
    ("Backup recovery", "backups/restore-check-appops_restore_20261113022643.json"),
)
for label, filename in records:
    record = json.loads(Path(filename).read_text())
    print(f"{label}: {record['result']}")
DEMO_EVIDENCE
```

The failed workflow was intentional: a CI run was supplied instead of a
staging deployment run. Backup and deployment were skipped.

Show the verified production recovery table in the backup runbook.
The local JSON files record earlier checks; reading them does not rerun
those checks. They are intentionally excluded from Git.

## 5. Show monitoring and limits — 90 seconds

Open the existing Grafana dashboard. Select staging and production and
show scrape status, traffic, server errors, and response times.
Use the monitoring runbook to explain the previously verified firing
and recovery notifications. Keep services running during this short demo.

Finish with the limits: one laptop, no API authentication, manual local
deployments and rollback, local backups, and local notifications. Actions
deployment was verified in the private lab and is gated off publicly.

## Evidence for a presentation

The [evidence walkthrough](evidence.md) includes the three recorded Grafana
views, links to CI and deployment runs, and the documented recovery result.
Use the original Actions pages for deployment and rejection evidence.

Keep credentials, environment-file contents, database archives, and
raw ticket data out of screenshots and Git.
