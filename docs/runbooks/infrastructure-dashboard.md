# Infrastructure and readiness dashboard

Open [Infrastructure and Readiness](http://localhost:3000/d/appops-infrastructure/infrastructure-and-readiness)
and sign in with the existing Grafana account. The dashboard is in the
Application Operations folder, alongside the application traffic dashboard.

The existing file provider checks the dashboard directory every 30 seconds.
Adding `monitoring/grafana/dashboards/infrastructure.json` uses that mounted
directory and does not require restarting Grafana or another service.

## Read the panels

| Panel | Meaning |
| --- | --- |
| Application readiness | Four HTTP checks: staging and production, direct and proxy |
| Monitoring exporters | Scrape status for Node Exporter, cAdvisor, and Blackbox Exporter |
| Readiness history | Ready is 1, failed probe is 0, unavailable probe data is a gap |
| WSL CPU usage | Average busy CPU across WSL logical CPUs over five minutes |
| WSL available memory | Available memory as a percentage of the WSL total |
| Filesystem available space | Available percentage for `/` and `/mnt/d` |
| Filesystem available bytes | Available bytes on those two filesystems |
| Container CPU usage | CPU-seconds per second; 1.0 represents one logical CPU core |
| Container working set | Memory working set, excluding inactive file cache |
| Working set against memory limit | Percentage of a positive limit below WSL total memory |

The **Readiness environment** selector affects only the readiness panels.
Host and container resources are shared by the local environments.

`/` is the WSL virtual filesystem. `/mnt/d` is the Windows D: volume.
Their free-space values are different measurements and must not be added
together. WSL CPU and memory panels do not measure all Windows processes.

Container legends use the first 12 characters of the current container ID.
The socket-free cAdvisor configuration does not supply Compose service names.
Map IDs to names with:

```bash
docker ps --format 'table {{.ID}}\t{{.Names}}'
```

Container recreation produces a new ID. The graphs retain historical
series within the selected time window; they are not a fixed service
inventory. Current points require fresh cgroup samples and a responding
exporter. Unlimited and host-sized limits are omitted from the limit panel.

## Verify the data

```bash
uv run --locked python scripts/check_infrastructure_dashboard.py
```

The command checks the layout, the JSON mounted inside Grafana, all ten
current panel queries, both readiness filters, the two filesystem series,
and current lab container coverage. It repeats the existing monitoring
verification and checks that container identities and start times remain
unchanged. It saves query results and the container-name map under
`backups/infrastructure-dashboard-check-*.json`.

This command does not authenticate to Grafana or prove that Grafana has
provisioned and rendered the dashboard. Complete that check in the browser:

1. Open the dashboard after the provider's polling interval.
2. Confirm four readiness routes and three exporters show UP.
3. Confirm all resource graphs display data and the two filesystem labels.
4. Select staging, then production; each selection should show two readiness
   routes. Restore All afterward.
5. Save screenshots of the status and resource panels for the evidence review.

The default time range is one hour. To inspect a historical drill, choose
a range containing that drill. CPU panels need at least two samples after
startup. Missing data is not a measured zero.

## Verified dashboard

On 13 November 2026, the mounted JSON matched and all ten queries passed.
The checks covered four readiness routes, three exporters, two filesystems,
CPU and working set for 16 containers, and nine containers with applicable
memory limits. Both environment-filter queries passed. Existing containers
were unchanged. Local evidence:
`backups/infrastructure-dashboard-check-20261113T115608574538Z.json`.

Browser screenshots showed the dashboard provisioned, the routes and
exporters UP, the staging-proxy outage in readiness history, and populated
host and container graphs. The first status panel rendered its labels
too small, so explicit text sizes and more panel space were added afterward.
A final browser check confirmed readable labels, all four readiness routes
and three exporters UP, and the recorded staging-proxy outage and recovery.
Metric expressions were unchanged. Repeated query checks passed and left
all 16 lab containers unchanged. Local evidence:
`backups/infrastructure-dashboard-check-20261113T120735332615Z.json`.
Recorded views are in the
[evidence walkthrough](../evidence.md#infrastructure-dashboard-screenshots).
