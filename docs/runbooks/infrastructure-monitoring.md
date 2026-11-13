# Infrastructure monitoring

This integration followed the Nginx, Ansible, and Python dependency-audit
work. The build order was host collection, container collection, readiness
probes, alert rules, delivery drills, and Grafana panels. The application
release remained `a56088c1b7bb`, version `0.1.2`.

## Prerequisites and scope

Use the existing WSL/Docker Desktop lab with staging, production, both
proxies, and the monitoring stack running. Their external Docker networks
must already exist. This is not a general-purpose host installer.

| Service | Source | Scope |
| --- | --- | --- |
| Node Exporter | Local `1.12.1-wsl.1` build | WSL CPU, memory, load, time, `/`, and `/mnt/d` |
| cAdvisor | Pinned 0.60.6 image | CPU and memory from Docker cgroup v2 paths |
| Blackbox Exporter | Pinned 0.29.1 image | Four direct/proxied readiness URLs |

Only Node Exporter publishes a host port, on `127.0.0.1:9100`. cAdvisor
and Blackbox Exporter are reached through Docker networks. The custom
Node Exporter build is described in [its build notes](../../deploy/node-exporter/README.md).
It uses an upstream procfs fix for the observed WSL mount format.

## Start in order

For the prepared lab, with the configuration files already present:

```bash
uv run --locked python scripts/start_node_exporter.py
uv run --locked python scripts/start_container_monitoring.py
uv run --locked python scripts/start_readiness_monitoring.py
uv run --locked python scripts/enable_monitoring_alerts.py
uv run --locked python scripts/check_infrastructure_dashboard.py
```

These startup commands deliberately recreate the selected exporter and,
where required, Prometheus to load its bind-mounted configuration. They
check protected containers before and after the operation. Do not run
another deployment concurrently.

To check an already running lab without recreating containers:

```bash
uv run --locked python scripts/start_readiness_monitoring.py --verify-only
uv run --locked python scripts/check_infrastructure_dashboard.py
```

The first command also checks host and container collection. Evidence
files remain under the ignored `backups/` directory. Screenshot and
result summaries are in the [evidence walkthrough](../evidence.md#infrastructure-monitoring-sequence).

## Configuration and CI checks

```bash
./scripts/check_monitoring.sh
./scripts/check_infrastructure.sh
```

The monitoring check validates Prometheus and Alertmanager configuration,
the original API alert tests, 29 infrastructure/readiness rule scenarios,
Blackbox configuration, and the ten infrastructure dashboard expressions.

The infrastructure check validates Compose configuration and builds the
local Node Exporter image. Its Dockerfile verifies Go modules, runs the
WSL mount regression and upstream filesystem tests, and builds the binary.
The check confirms the non-root image user and reported version using an
isolated container without host mounts or networking. It does not restart
the running exporter. The same commands are included in CI before image
publishing; the first CI run for this integration is still pending.

CI does not prove visibility into the user's WSL host. The live checks
compare exporter values with WSL, require fresh container samples, and
verify real readiness routes. The two database integration tests remain
part of the existing CI database job.

## Operational checks

- [Container monitoring](container-monitoring.md): cgroup access and ID mapping.
- [Readiness monitoring](readiness-monitoring.md): HTTP/body contract and routes.
- [Monitoring alerts](monitoring-alerts.md): thresholds and controlled delivery drills.
- [Infrastructure dashboard](infrastructure-dashboard.md): panel meanings and visual checks.

Alerts and their receiver run on the same laptop. They cannot provide
off-machine notification when the laptop or monitoring stack is down.
Disk and memory thresholds were tested with synthetic series; the live
drills did not fill disks or exhaust memory.
