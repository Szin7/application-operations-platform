# HTTP readiness monitoring

Blackbox Exporter checks `/health/ready` through four internal routes:

| Environment | Route | Target |
| --- | --- | --- |
| Staging | Direct | `application-operations-staging-api-1:8000` |
| Staging | Nginx | `application-operations-proxy-staging-1:8080` |
| Production | Direct | `application-operations-production-api-1:8000` |
| Production | Nginx | `application-operations-proxy-production-1:8080` |

The HTTP module requires status 200 and the current readiness body,
`{"status":"ready"}`, allowing whitespace. It does not follow redirects.
The module timeout is three seconds; Prometheus probes every 15 seconds.
If the readiness response contract changes, update the module and its
checks together.

The application readiness endpoint queries the database. These probes
therefore cover that query and, for the Nginx targets, proxy forwarding.
They do not test every ticket operation or external browser connectivity.

## Start and verify

```bash
uv run --locked python scripts/start_readiness_monitoring.py
```

The command validates the configuration, recreates only Blackbox Exporter,
and checks its runtime restrictions. A temporary HTTP fixture on the
monitoring network verifies four cases:

| Fixture response | Expected probe result |
| --- | --- |
| HTTP 200 with the ready body | Success |
| HTTP 200 with `{"status":"not_ready"}` | Failure |
| HTTP 503 with the ready body | Failure |
| HTTP 302 redirect to the ready fixture | Failure |

The fixture uses the immutable image ID of the running Python alert
receiver. It has no host port and is removed after the checks. It does not
change the application or database services.

After the four real routes pass, the command recreates only Prometheus
to load the changed bind-mounted configuration. It verifies fresh probe
results, repeats host and container checks, and checks that the other lab
containers stayed unchanged. Successful evidence is saved under
`backups/readiness-monitoring-check-*.json`.

To check the running probes without creating or recreating containers:

```bash
uv run --locked python scripts/start_readiness_monitoring.py --verify-only
```

## Read the results

```promql
probe_success{job="application-readiness"}
probe_http_status_code{job="application-readiness"}
probe_duration_seconds{job="application-readiness"}
```

Each series has `environment` and `route` labels. `route` is `direct` or
`proxy`. `instance` is the complete target URL.

`up{job="application-readiness"}` describes whether Prometheus collected
the probe result. A reachable exporter can return a failed probe while
`up` remains 1. Application readiness must be judged using `probe_success`.
The separate `readiness-exporter` job monitors the exporter itself.

## Runtime scope

The pinned exporter runs as UID/GID 65534 with a read-only root filesystem,
all capabilities dropped, and no-new-privileges. It has a 64 MiB memory
limit, a 0.25 CPU limit, and a 64 PID limit. Its only bind mount is the
read-only probe configuration. It publishes no host port and joins the
monitoring, staging, and production networks to reach the four targets.

See [Monitoring alerts](monitoring-alerts.md) for readiness failure,
exporter availability, and missing-target rules. The existing API scrape
alert remains active.

## Verified collection

On 13 November 2026, all four fixture cases and all four real readiness
routes passed. Prometheus received fresh results for each route. Host
metrics and all 16 running lab containers passed their checks, and the
protected containers were unchanged. Local evidence:
`backups/readiness-monitoring-check-20261113T074611176825Z.json`.

After a laptop shutdown, all 16 existing containers were started again
with their IDs and images preserved. Readiness, host, and container checks
passed again. Local evidence:
`backups/readiness-monitoring-check-20261113T111736928158Z.json`.
