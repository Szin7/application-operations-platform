# Monitoring alerts

Prometheus evaluates the rules every 15 seconds. Conditions must remain
true for the stated delay before an alert fires. A brief failure that
recovers within that delay does not fire. The existing API scrape alert
is retained.

| Alert | Condition | Delay |
| --- | --- | --- |
| `ReadinessCheckFailed` | A readiness probe fails, its scrape fails, or a successful scrape lacks the probe result | 1 minute |
| `ReadinessTargetsMissing` | The readiness target count differs from four | 1 minute |
| `InfrastructureExporterDown` | Host, container, or readiness exporter scrape fails | 1 minute |
| `InfrastructureTargetsMissing` | The infrastructure exporter target count differs from three | 1 minute |
| `HostCollectionFailed` | A responding host exporter reports a collector or filesystem error | 1 minute |
| `HostCollectorsMissing` | A responding host exporter does not report five collector status series | 1 minute |
| `HostCpuBusy` | Five-minute average WSL CPU usage stays above 90% | 5 minutes |
| `HostMemoryLow` | WSL available memory stays below 10% | 5 minutes |
| `HostFilesystemLowSpace` | Available space on `/` or `/mnt/d` stays below 10%, with successful collection | 5 minutes |
| `ContainerMemoryHigh` | Fresh container working set stays above 90% of a positive limit below WSL total memory | 5 minutes |

These are initial lab thresholds, not service-level objectives. Resource
rules require their exporters to be up. CPU uses `rate()` so counter
resets after restarts are handled. Container-memory evaluation also
requires the host memory total and a responding host exporter.

## Validate and load

```bash
./scripts/check_monitoring.sh
uv run --locked python scripts/enable_monitoring_alerts.py
```

The startup command validates the configuration and rule tests, recreates
only Prometheus, and repeats readiness, host, and container verification.
It verifies that all 11 alert rules, including `ApiScrapeFailed`, are loaded
with the expected delays and evaluate without errors. Current pending or
firing alerts are reported, not treated as a configuration failure.

The command also prints Grafana's total usage, working set, and limit to
distinguish cache-heavy startup usage from sustained memory pressure.
It does not change any resource limits or stop an application service.
Evidence is saved in `backups/monitoring-alerts-check-*.json`.

The new test file has 29 synthetic scenarios covering sustained failures,
recovery, transient failures, missing series, counter resets, resource
threshold boundaries, cache-heavy memory usage, unlimited containers,
and stale container samples. CI runs these through the same monitoring
check script used locally.

## Check local notification delivery

Run this only while the full lab is healthy, with no other deployment or
container changes in progress. Keep the terminal and Docker Desktop open.
The original production ticket must be recorded in
`backups/rollback-check.json`.

```bash
uv run --locked python scripts/check_alert_delivery.py
```

The command runs two outages in order:

1. Stop the existing staging proxy, wait for `ReadinessCheckFailed` for
   `staging/proxy` and its firing webhook, restart the same container,
   and wait for the matching resolved webhook.
2. Stop the existing host exporter, wait for `InfrastructureExporterDown`
   for `wsl-host` and its firing webhook, restart the same container,
   and wait for its matching resolved webhook.

Each notification wait is limited to four minutes. Each restart health
wait is limited to two minutes. Progress is printed during the waits.
The staging proxy is deliberately unavailable during the first outage;
the direct staging API and both production routes must stay ready.
All application routes remain available during the exporter outage.

The script checks protected container identities, images, start times,
and health states, and compares every returned field of the original
production ticket through both production routes. Each tested container
keeps its ID and image, but its start time changes as expected.

Receiver events must be new, match the selected labels, and refer to the
same alert fingerprint and start time for firing and recovery. Individual
alert status is checked even when another alert keeps the group firing.
The script also checks the corresponding Prometheus alert state.

The stopped container is restarted in a `finally` block on success,
failure, timeout, Ctrl+C, or a normal termination signal. Forced process
termination or a machine shutdown cannot run Python cleanup. If cleanup
fails, start the two existing containers explicitly and inspect their
health before continuing:

```bash
docker start application-operations-proxy-staging-1 \
  application-operations-infrastructure-node-exporter-1
uv run --locked python scripts/start_readiness_monitoring.py --verify-only
```

The script saves progress, matching notifications, and its final result
in `backups/alert-delivery-check-*.json`, including failures. After both
drills it repeats readiness, host, and container checks. Unit tests use
mocked commands and do not stop containers or send notifications.

## Verified rule loading

On 13 November 2026, configuration checks and both rule test suites
passed on the lab host. All 11 rules loaded with healthy evaluations and
were inactive. Only Prometheus was recreated; the other lab containers
were unchanged. Readiness, host, and container checks passed.

Grafana reported a 361.23 MiB working set against its 512 MiB limit,
while total usage was 477.07 MiB. No memory-limit change was made.
Local evidence: `backups/monitoring-alerts-check-20261113T113531130273Z.json`.

## Verified firing and recovery delivery

On 13 November 2026, both controlled outages passed in sequence:

- The staging proxy outage produced a `ReadinessCheckFailed` firing
  notification and a matching resolved notification after recovery.
- The host exporter outage produced an `InfrastructureExporterDown`
  firing notification and a matching resolved notification after recovery.
- Both tested containers recovered with their original IDs and images.
- Production stayed ready through both routes, and every returned field
  of the original production ticket matched throughout the checks.
- The final readiness, host, and container verification passed.

Local evidence: `backups/alert-delivery-check-20261113T114254887139Z.json`.
The 18 delivery-check unit tests also passed on the lab host.

## Investigate a firing alert

- For readiness, check both `up` and `probe_success` for the affected
  environment and route. A failed probe can coexist with a successful
  scrape. Compare direct and proxied routes, then check API, proxy, and
  database logs as appropriate.
- For exporter or collection errors, inspect the target and collector
  status before interpreting missing resource data as healthy.
- For memory pressure, map `container_id` to the current container using
  `docker ps --no-trunc`. Inspect working set, configured limit, workload,
  and any OOM events before changing limits.
- For low disk space, identify the mountpoint. `/` is the WSL virtual
  filesystem; `/mnt/d` is the Windows D: volume. Do not prune database
  volumes or delete recovery evidence to clear an alert.

## Delivery and limitations

The existing Alertmanager route sends firing and resolved notifications
to the local webhook receiver. Its group wait is 10 seconds and group
interval is 30 seconds. Scrape, evaluation, and grouping intervals add
delay beyond the rule's `for` duration.

An exporter outage can also produce readiness-check alerts. This small
lab keeps that overlap visible; it does not configure alert inhibition.
Target-count rules detect missing or extra targets, not every possible
incorrect target substitution. Verification scripts check the configured
route identities separately.

cAdvisor identifies containers by ID and does not supply a stable desired
service inventory. These rules do not detect every individually stopped
container. API, database-query, and proxy failures are covered by the
application checks. Unlimited or host-sized container memory limits are
excluded from the percentage-of-limit rule.

Prometheus cannot report its own outage or a laptop shutdown through this
same local pipeline. External monitoring and off-machine notifications
are outside the current setup. The webhook receiver keeps recent events
in memory, so save drill evidence before restarting it.

Synthetic tests do not prove live notification delivery. The two live
drills exercise readiness and exporter alerts through the local receiver;
they do not force CPU, memory, or disk exhaustion to test resource alerts.
