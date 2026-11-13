# Container resource monitoring

cAdvisor collects CPU and memory counters from Docker's cgroup v2 hierarchy.
Prometheus scrapes it over the existing monitoring network. cAdvisor has
no published host port, runtime socket mounts, bind mounts, added Linux
capabilities, or privileged mode. It uses the host cgroup namespace and
runs as the image's default root user with a read-only root filesystem.

The collector has a 256 MiB memory limit, a 0.5 CPU limit, and a 128 PID
limit. It samples every 10 seconds; Prometheus scrapes every 15 seconds.

## Why this configuration

The lab uses Docker Desktop's containerd snapshotter. Its runtime socket
was not accessible through the tested bind paths. A temporary cAdvisor
0.60.6 container successfully collected CPU and memory metrics for the
staging and production APIs and databases directly from `/docker/<id>`
cgroups on 13 November 2026. The probe was removed, and the existing lab
containers were unchanged.

This configuration uses that tested cgroup collection path. Runtime
factory warnings about unavailable Docker or containerd sockets can occur
at startup; collection is accepted only when the expected cgroup metrics
are present and fresh. An HTTP health check alone is insufficient.

## Start and verify

From the repository root:

```bash
uv run --locked python scripts/start_container_monitoring.py
```

The script validates the configuration, starts only cAdvisor, and verifies
its direct metrics before recreating only Prometheus to load the changed
configuration. It then verifies the ingested container metrics, repeats
the existing host checks, and checks all four application readiness URLs.
Other running application lab containers must retain their IDs, images,
start times, and health states. Successful checks write local evidence
under `backups/container-monitoring-check-*.json`.

To repeat verification without changing containers:

```bash
uv run --locked python scripts/start_container_monitoring.py --verify-only
```

## Interpret the metrics

Job: `container-resources`. Instance: `appops-docker`. Scope: `docker-desktop`.

```promql
rate(container_cpu_usage_seconds_total{job="container-resources"}[2m])
```

This is CPU consumption in cores: 1 means one logical CPU in use. The
underlying counter is cumulative CPU time, not a CPU percentage.

```promql
container_memory_usage_bytes{job="container-resources"}
container_memory_working_set_bytes{job="container-resources"}
```

Memory usage and working set have different definitions. Neither should
be presented as an exact match for every value shown by `docker stats`.

## Scope and limits

- Metrics identify containers by their full `container_id`. The verifier
  prints and records a current mapping to Docker container names.
- Compose service labels and image metadata are not available from the
  raw collector. Container IDs change when containers are recreated;
  rerun verification to obtain the current mapping.
- The collector sees Docker cgroups, including containers outside this
  repository. The verifier checks the running `application-operations-`
  containers. Prometheus retains the selected CPU and memory series for
  all discovered Docker container IDs.
- Network, container filesystem, process, and physical device metrics
  are outside this collector's configured scope. Host filesystem capacity
  is checked separately through Node Exporter.
- This setup has been developed for the observed Docker Desktop cgroup
  layout. Validate the layout and runtime access before using it elsewhere.

## Verified persistent collection

On 13 November 2026, cAdvisor's runtime restrictions and network scope
passed. Direct and ingested CPU, memory, and freshness checks passed for
all 15 running lab containers. Host metrics and all four application
readiness checks passed, and the protected containers were unchanged.

Local evidence:
`backups/container-monitoring-check-20261113T073505550400Z.json`.

The newly recreated Prometheus container appeared after the collector
discovery and scrape delay. Verification waited for its metrics rather
than excluding it from the check.
