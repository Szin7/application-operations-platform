# Project evidence

This page brings together the recorded lab checks and dashboard screenshots.
Staging, production, databases, and monitoring ran on one laptop. There is
no public application or Grafana endpoint.

CI checks and image publishing remain enabled in the public repository.
The Actions deployment and runner-check jobs are intentionally gated off
by their private-repository condition. The deployment runs below were
completed while the repository was private.

## Delivery checks

| Check | Recorded result | Evidence |
| --- | --- | --- |
| CI and image publishing | Passed for commit `e024a55` | [Run 43354287536](https://github.com/Szin7/application-operations-platform/actions/runs/43354287536) |
| CI for the deployed release | Passed for release `a56088c1b7bb` | [Run 43302633612](https://github.com/Szin7/application-operations-platform/actions/runs/43302633612) |
| Staging deployment | Exact release verified; production not restarted | [Run 43344606433](https://github.com/Szin7/application-operations-platform/actions/runs/43344606433) |
| Production promotion | Backup created; original ticket preserved; staging not restarted | [Run 43347528825](https://github.com/Szin7/application-operations-platform/actions/runs/43347528825) |
| Invalid promotion | Expected rejection before backup and deployment | [Run 43351535975](https://github.com/Szin7/application-operations-platform/actions/runs/43351535975) |

The CI run for documentation commit `e024a55` did not deploy a new release.
The recorded staging and production deployments used release
`a56088c1b7bb`, application version `0.1.2`.

### Why one workflow is red

Run `43351535975` deliberately supplied a CI run where a successful staging
deployment run was required. It failed at **Read the successful staging
deployment** with:

> Choose a successful staging deployment from main.

The backup and deployment steps were skipped. A separate local comparison
confirmed that the staging and production containers, readiness, versions,
production ticket, saved release, and backup directories were unchanged.
The verification passed because the invalid request was rejected.

See the [rejection record](runbooks/actions-deployments.md#verified-rejection-check)
for the scope and local evidence filename. This was one wrong-workflow test,
not exhaustive testing of every invalid input.

## Recovery checks

On 13 November 2026, production backup `20261113T014802Z-JkSafR` was
restored into a separate database in the test PostgreSQL container.

| Check | Recorded result |
| --- | --- |
| Archive checksum | Passed |
| Recovered database | `appops_restore_20261113022643` |
| Migration revision | `0001` |
| Application access | Verified as `appops_test_app` |
| Recovered ticket | One ticket; every returned field matched |
| Recovered readiness | Passed through FastAPI TestClient |
| Running production | Containers unchanged; readiness and original ticket passed |

These results are documented in the
[production recovery runbook](runbooks/backup-restore.md#verified-production-backup-recovery).
The database archive and raw local evidence JSON are excluded from Git.
Recovery covered the current schema and one demonstration ticket; production
was not switched to the recovered database.

The earlier [application rollback exercise](runbooks/deployment-rollback.md#verified-exercise-12-november-2026)
restored the previous application image and preserved the original ticket.
It used an unchanged database schema.

## Monitoring screenshots

Captured from the local Grafana dashboard on 13 November 2026. These are
recorded views of light demo traffic, not a performance benchmark or live
service status.

### Scrape status and traffic

Both production and staging scrape targets show **UP**, with application
request traffic recorded for each environment.

![Grafana showing production and staging scrape targets UP and request traffic](images/grafana-overview.png)

### Errors and response time

The plotted server-error percentages are zero. The earlier p95 response-time
samples are approximately 23–24 ms for production and 4–5 ms for staging.
The sparse samples do not establish comparative performance. Empty intervals
are not measured zeros; see the [monitoring runbook](runbooks/monitoring.md#read-the-dashboard).

![Grafana showing server-error percentages and p95 response times](images/grafana-errors-latency.png)

### Routes and status codes

The dashboard groups traffic by environment and route template, and records
HTTP 200 responses for the displayed requests.

![Grafana showing requests grouped by route and HTTP status](images/grafana-routes-status.png)

For a short walkthrough, follow the [five-minute demo](demo.md).
