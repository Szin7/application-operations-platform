# Application monitoring

Prometheus collects metrics from the staging and production APIs every
15 seconds. Grafana reads those metrics through a provisioned data source.

## Local services

| Service | Version | Address |
| --- | --- | --- |
| Prometheus | 3.13.5 | http://localhost:9090 |
| Grafana | 13.3.1 | http://localhost:3000 |

Both services publish their ports on the local loopback address.

The staging and production environments must already be running.
Prometheus connects to their existing Docker networks. Grafana connects
to Prometheus through the monitoring network.

## Grafana credentials

Use the existing `.env.grafana` file if it has already been created.

For a new checkout, copy the template and set a password before starting:

```bash
cp -n deploy/grafana.env.example .env.grafana
chmod 600 .env.grafana
nano .env.grafana
```

Set `GF_SECURITY_ADMIN_USER` and `GF_SECURITY_ADMIN_PASSWORD`.
Use a password of at least 12 characters. Single-quote the password
value to prevent dollar signs from being interpolated.

The file is excluded from Git and Docker build contexts.

Grafana uses these settings to create its first administrator account.
Changing the file later does not reset an existing account's password.

## Start monitoring

Run from the repository root:

```bash
docker compose -f compose.monitoring.yaml -f compose.grafana.yaml \
  config --quiet

docker compose -f compose.monitoring.yaml -f compose.grafana.yaml \
  up -d --wait --wait-timeout 180
```

Check the services:

```bash
docker compose -f compose.monitoring.yaml -f compose.grafana.yaml ps
```

Open the [Application Operations dashboard](http://localhost:3000/d/appops-overview/application-operations).

Sign in using the credentials from `.env.grafana`.

## Read the dashboard

Use the Environment selector to show staging, production, or both.

| Panel | Meaning |
| --- | --- |
| API scrape status | Whether Prometheus can collect the API's metrics |
| Request rate | Average application requests per second over five minutes |
| Server errors (%) | HTTP 5xx responses as a percentage of application requests over five minutes |
| Response time (p95) | Estimated 95th percentile response time over five minutes |
| Requests by route | Request rate grouped by route template and environment |
| Requests by status | Request rate grouped by HTTP status and environment |

Traffic panels exclude health-check routes and `/metrics`.
Database readiness is checked separately at `/health/ready`.

A short traffic burst is averaged across the five-minute query window.
When there are no requests, error percentages and response-time panels
can show gaps. A missing value should not be read as a measured zero.

## Scrape alerts

`ApiScrapeFailed` becomes pending when an API scrape fails. It fires
after the failure continues for one minute and clears after scraping
recovers. Scrape and evaluation intervals affect when each change appears.

This alert checks access to `/metrics`. It does not check database
readiness or send notifications.

Run the configuration checks and alert tests:

```bash
./scripts/check_monitoring.sh
```

The tests cover a brief failure, a sustained failure, and recovery.
They also check that a healthy production target does not raise an alert.
The CI workflow runs the same command.

## Configuration files

- `monitoring/prometheus.yml`: scrape targets, environment labels, and rule files.
- `monitoring/rules/api.yml`: API scrape alert.
- `monitoring/tests/api.test.yml`: alert test cases.
- `scripts/check_monitoring.sh`: configuration checks and alert tests.
- `monitoring/grafana/provisioning/datasources/prometheus.yml`: Grafana's Prometheus connection.
- `monitoring/grafana/provisioning/dashboards/application.yml`: dashboard provider.
- `monitoring/grafana/dashboards/application.json`: panels, queries, and environment selector.
- `compose.monitoring.yaml`: Prometheus service, storage, and networks.
- `compose.grafana.yaml`: Grafana service, storage, and configuration mounts.

Edit the dashboard JSON in the repository. Grafana checks for dashboard
file changes every 30 seconds. UI changes cannot be saved to this
provisioned dashboard.

## Storage and resources

Each monitoring container has a 512 MB memory limit.

Prometheus keeps metrics in a named volume, with retention settings of
two days and 512 MB. Working files and compaction require additional
disk space, so the retention size is not a hard total-disk limit.

Grafana stores its database in a separate named volume.

Stop monitoring while keeping the stored data:

```bash
docker compose -f compose.monitoring.yaml -f compose.grafana.yaml stop
```

## Troubleshooting

Read recent logs:

```bash
docker compose -f compose.monitoring.yaml -f compose.grafana.yaml \
  logs --tail=80 prometheus grafana
```

If a scrape fails, check the target's error in Prometheus and confirm
that its API container is running.

If traffic panels are empty, make requests to the application and allow
several scrape intervals for rate calculations.

## Verified locally

On 13 November 2026, Nepal time:

- Both APIs were running version 0.1.2.
- Prometheus collected metrics from staging and production.
- Grafana queried both environments through its provisioned data source.
- The dashboard loaded all six panels from the repository configuration.
- Every panel query returned finite values for both environments.
- Browser checks showed both targets UP and graphs for the sample traffic.

Verification used a short burst of ticket-list requests.

A separate recovery check stopped the staging API and confirmed:

- The scrape alert moved from inactive to pending, then firing.
- Staging recovered with the same container and image.
- The alert cleared after scraping recovered.
- Production readiness checks passed throughout the wait loops.
- The production container was not restarted.

Alert notification delivery has not been configured yet.
