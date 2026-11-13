# Project evidence

This page brings together the recorded lab checks and dashboard screenshots.
Staging, production, databases, and monitoring ran on one laptop. There is
no public application or Grafana endpoint.

CI checks and image publishing remain enabled in the public repository.
The Actions deployment and runner-check jobs are intentionally gated off
by their private-repository condition. The Actions deployment runs below
were completed while the repository was private. The later Ansible rehearsals
ran locally in WSL.

## Delivery checks

| Check | Recorded result | Evidence |
| --- | --- | --- |
| CI and image publishing | Passed for Ansible integration commit `598ba82` | [Run 43370353727](https://github.com/Szin7/application-operations-platform/actions/runs/43370353727) |
| CI for the deployed release | Passed for release `a56088c1b7bb` | [Run 43302633612](https://github.com/Szin7/application-operations-platform/actions/runs/43302633612) |
| Staging deployment | Exact release verified; production not restarted | [Run 43344606433](https://github.com/Szin7/application-operations-platform/actions/runs/43344606433) |
| Production promotion | Backup created; original ticket preserved; staging not restarted | [Run 43347528825](https://github.com/Szin7/application-operations-platform/actions/runs/43347528825) |
| Invalid promotion | Expected rejection before backup and deployment | [Run 43351535975](https://github.com/Szin7/application-operations-platform/actions/runs/43351535975) |

The CI run for Ansible integration commit `598ba82` did not deploy a new application release.
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

## Nginx integration

On 13 November 2026, Nginx was added after the recorded deployment and
recovery checks. The order was image verification, staging proxy and routing
checks, production proxy and routing checks, then runtime verification.
The application release remained `a56088c1b7bb`, version `0.1.2`.

Both proxies passed readiness, route/query forwarding, matching 404 and 422
responses, and rejection of oversized requests with 413. Runtime checks
confirmed the non-root user, read-only settings, capability and privilege
restrictions, resource limits, rotating logs, loopback ports, and separate
application networks. Existing API and database containers stayed unchanged
across proxy startup.

The local record `backups/proxy-check-20261113T042015231868Z.json` contains
runtime, request-size, and readiness checks plus configuration hashes.
Routing and startup comparisons were reviewed separately from terminal
output. See the [Nginx runbook](runbooks/reverse-proxy.md) for details and
limits. This integration did not rerun the earlier deployment, rollback,
monitoring alert, or backup-recovery exercises.

## Ansible deployment rehearsals

Ansible was added after Nginx and verified on 13 November 2026. The sequence
was preflight, staging check mode and live run, then production check mode
and live run. All runs finished with zero failures and unreachable hosts.
Both live runs retained release `a56088c1b7bb`, version `0.1.2`.

| Check | Recorded result |
| --- | --- |
| Check mode | Zero changes for staging and production; deployment and backup skipped |
| Staging rehearsal | Passed; two reported changes: deployment procedure and evidence file |
| Production rehearsal | Passed; three reported changes: backup, deployment procedure, and evidence file |
| Production backup | `backups/20261113T050247Z-OWcabu`, created before deployment |
| Post-deployment checks | Readiness, image/version, saved release, original production ticket, and protected containers passed |

Local evidence records, in execution order:

- `backups/ansible-deploy-staging-20261113T050021364380Z.json`
- `backups/ansible-deploy-production-20261113T050313711191Z.json`

The filenames use UTC. The records contain configuration hashes and
verification results, without credentials or ticket contents, and remain
excluded from Git. See [Deploy with Ansible](runbooks/ansible-deployments.md)
for the full procedure and recaps. These same-release rehearsals do not
establish upgrade, new-migration, container-replacement, or failure-recovery
behavior. The newly created backup was not restored in this exercise.

## Python dependency baseline

After the Ansible rehearsals, the locked runtime and development dependencies
were audited in WSL on 13 November 2026 using `pip-audit 2.10.1`.
The scan covered 31 applicable Python packages, skipped none, and reported
no known vulnerabilities. The checkout was `598ba82`, and the working tree
remained clean.

Evidence was saved locally in
`backups/dependency-audit-20261113T052751Z-HgBtxd`. This is a point-in-time
check of the checkout's lockfile, not a scan of the running container images.
See [Python dependency checks](runbooks/dependency-checks.md) for the CI gate,
report files, and coverage limits. The baseline preceded the reusable CI
check; a later workflow run is needed to verify that integration on GitHub.

## Infrastructure monitoring sequence

The following checks ran on 13 November 2026, after the dependency-audit
integration. Times below are UTC, matching the local evidence filenames.
All services remained on the same laptop.

| Time (UTC) | Step | Recorded result |
| --- | --- | --- |
| 06:57 | WSL host exporter | Five collectors passed; 12 CPUs, memory total, and two filesystem identities/capacities matched WSL |
| 07:05 | Host scrape | Prometheus ingested the checked host metrics |
| 07:35 | Container collection | CPU, memory, and freshness passed for the then-running 15 containers |
| 07:46 | Readiness collection | Four HTTP/body probes passed; all 16 lab containers were checked |
| 11:17 | Resume after the pause | All 16 existing containers recovered with preserved IDs and images; collection and readiness passed again |
| 11:35 | Alert rules | All 11 rules evaluated without errors and were inactive |
| 11:42–11:47 | Delivery drills | Staging proxy, then host exporter: firing and matching recovery notifications received |
| 11:56 | Dashboard queries | Ten panel queries and both readiness filters passed; all existing containers unchanged |

The two delivery drills deliberately restarted only their selected targets.
Production stayed ready through direct and proxied routes, and every
returned field of the original production ticket matched throughout.
The running application release remained `a56088c1b7bb`, version `0.1.2`.

Key local records:

- `backups/node-exporter-check-20261113T065751619929Z.json`
- `backups/container-monitoring-check-20261113T073505550400Z.json`
- `backups/readiness-monitoring-check-20261113T074611176825Z.json`
- `backups/readiness-monitoring-check-20261113T111736928158Z.json`
- `backups/monitoring-alerts-check-20261113T113531130273Z.json`
- `backups/alert-delivery-check-20261113T114254887139Z.json`
- `backups/infrastructure-dashboard-check-20261113T115608574538Z.json`

These raw records stay local. See the [infrastructure runbook](runbooks/infrastructure-monitoring.md)
for startup and verification, and the [alert runbook](runbooks/monitoring-alerts.md)
for the distinction between synthetic resource tests and live delivery drills.
The monitoring integration's first CI run is pending; the local results
above are not a claim that GitHub has already checked this change.

## Infrastructure dashboard screenshots

Captured on 13 November 2026 from the running local dashboard. These views
show measured lab usage, not a benchmark. Gaps during the host-exporter
outage represent unavailable data, not measured zeros.

### Readiness and exporter status

The final view shows four readiness routes and three exporters UP, with
readable status labels. Readiness history records the deliberately stopped
staging proxy dropping to zero and recovering. The direct staging route
and both production routes stayed ready during that drill.

![Grafana showing four readiness routes and three exporters UP, with the staging proxy outage and recovery](images/grafana-infrastructure-readiness.png)

### Host resources and filesystem capacity

The screenshot shows approximately 7.33% WSL CPU usage and 78.4% available
memory at its right edge. The root filesystem reports virtual WSL capacity;
Windows D: is shown separately as `/mnt/d`, with about 80.6 GiB available.

![Grafana WSL CPU, memory, and separate root and Windows D filesystem capacity](images/grafana-host-resources.png)

### Container resources

CPU is plotted in cores, memory as working set, and limited containers
as a percentage of their configured memory limit. Legends use current
container IDs because the raw cgroup collector does not provide service names.
Use `docker ps --format 'table {{.ID}}\t{{.Names}}'` to map them to names.

![Grafana container CPU, working set, and working set against memory limits](images/grafana-container-resources.png)

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
