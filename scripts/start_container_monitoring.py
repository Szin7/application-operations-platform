"""Start socket-free cAdvisor collection and verify its Prometheus samples."""

import argparse
import hashlib
import json
import math
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from prometheus_client.parser import text_string_to_metric_families
from start_node_exporter import output, readiness, snapshot
from verify_host_scrape import query, single, value
from verify_host_scrape import verify as verify_host

ROOT = Path(__file__).resolve().parents[1]
CADVISOR = "application-operations-infrastructure-cadvisor-1"
CADVISOR_IMAGE = "ghcr.io/google/cadvisor@sha256:b8e7d1093144fd088f425ff003d75a4aa405de075db78dae3bc563730b1bd07a"
PROMETHEUS = "application-operations-monitoring-prometheus-1"
INFRA = ["docker", "compose", "-f", "compose.infrastructure.yaml"]
MONITORING = [
    "docker",
    "compose",
    "-f",
    "compose.monitoring.yaml",
    "-f",
    "compose.grafana.yaml",
    "-f",
    "compose.alerting.yaml",
]
SELECTOR = '{job="container-resources",instance="appops-docker",scope="docker-desktop"}'
METRICS = (
    "container_cpu_usage_seconds_total",
    "container_memory_usage_bytes",
    "container_last_seen",
)


def running_lab():
    ids = output(
        "docker", "ps", "--filter", "name=application-operations-", "-q"
    ).split()
    if not ids:
        raise RuntimeError("No running lab containers found.")
    return snapshot(ids)


def check_samples(samples, targets):
    rows = {}
    now = time.time()
    for name, record in targets.items():
        group = f"/docker/{record['id']}"
        numbers = []
        for metric in METRICS:
            key = (metric, group)
            if key not in samples or not math.isfinite(samples[key]):
                raise RuntimeError(f"Missing or non-finite {metric} for {name}")
            numbers.append(samples[key])
        cpu, memory, last_seen = numbers
        if cpu < 0 or memory <= 0 or not 0 <= now - last_seen < 45:
            raise RuntimeError(f"Invalid or stale container metrics for {name}")
        rows[name] = {
            "container_id": record["id"],
            "cpu_total_seconds": cpu,
            "memory_usage_bytes": memory,
            "last_seen": last_seen,
        }
    return rows


def read_direct():
    text = output(
        "docker",
        "exec",
        CADVISOR,
        "wget",
        "-q",
        "-T",
        "5",
        "-O",
        "-",
        "http://127.0.0.1:8080/metrics",
    )
    samples = {}
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name in METRICS:
                key = (sample.name, sample.labels.get("id"))
                if key in samples:
                    raise RuntimeError(f"Duplicate metric: {key}")
                samples[key] = sample.value
    return samples


def read_prometheus():
    if value(single("up" + SELECTOR)) != 1:
        raise RuntimeError("cAdvisor scrape target is not up.")
    samples = {}
    for metric in METRICS:
        for sample in query(metric + SELECTOR):
            labels = sample["metric"]
            group = labels.get("id", "")
            if group != f"/docker/{labels.get('container_id', '')}":
                raise RuntimeError(f"Container ID relabelling differs: {labels}")
            key = (metric, group)
            if key in samples:
                raise RuntimeError(f"Duplicate ingested metric: {key}")
            samples[key] = value(sample)
    return samples


def wait_for_samples(reader, targets):
    deadline = time.monotonic() + 90
    while True:
        try:
            return check_samples(reader(), targets)
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Container verification timed out: {exc}") from exc
            print(f"Waiting for fresh container metrics: {exc}", flush=True)
            time.sleep(5)


def check_runtime():
    details = json.loads(output("docker", "inspect", CADVISOR))[0]
    host = details["HostConfig"]
    if (
        details["Config"]["Image"] != CADVISOR_IMAGE
        or host["Privileged"]
        or not host["ReadonlyRootfs"]
        or host["CgroupnsMode"] != "host"
        or host.get("CapAdd")
        or "ALL" not in (host.get("CapDrop") or [])
        or "no-new-privileges:true" not in (host.get("SecurityOpt") or [])
        or host["Memory"] != 256 * 1024**2
        or host["NanoCpus"] != 500_000_000
        or host["PidsLimit"] != 128
        or details["Mounts"]
        or any(details["NetworkSettings"]["Ports"].values())
        or set(details["NetworkSettings"]["Networks"])
        != {"application-operations-monitoring_default"}
    ):
        raise RuntimeError(
            "cAdvisor runtime restrictions differ from the intended configuration."
        )
    print("cAdvisor runtime restrictions and network scope: passed", flush=True)
    return snapshot([CADVISOR])[CADVISOR]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Check the running services without recreating containers",
    )
    args = parser.parse_args()
    before = running_lab()
    required = {
        f"application-operations-{env}-{service}-1"
        for env in ("staging", "production")
        for service in ("api", "db")
    }
    if not required.issubset(before):
        raise RuntimeError(
            "Both staging and production application stacks must be running."
        )
    if not args.verify_only:
        before.pop(PROMETHEUS, None)
        before.pop(CADVISOR, None)
    protected = [record["id"] for record in before.values()]
    readiness()
    try:
        if not args.verify_only:
            subprocess.run(INFRA + ["config", "--quiet"], cwd=ROOT, check=True)
            subprocess.run(
                ["bash", "scripts/check_monitoring.sh"], cwd=ROOT, check=True
            )
            subprocess.run(
                INFRA
                + [
                    "up",
                    "-d",
                    "--no-deps",
                    "--no-build",
                    "--pull",
                    "never",
                    "--wait",
                    "--wait-timeout",
                    "90",
                    "cadvisor",
                ],
                cwd=ROOT,
                check=True,
            )
            wait_for_samples(read_direct, running_lab())
            subprocess.run(
                MONITORING
                + [
                    "up",
                    "-d",
                    "--no-deps",
                    "--force-recreate",
                    "--pull",
                    "never",
                    "--wait",
                    "--wait-timeout",
                    "120",
                    "prometheus",
                ],
                cwd=ROOT,
                check=True,
            )

        runtime = check_runtime()
        targets = running_lab()
        direct = wait_for_samples(read_direct, targets)
        ingested = wait_for_samples(read_prometheus, targets)
        host_result = verify_host()
        # Confirm that a container was not replaced while its metrics were checked.
        current = running_lab()
        if {n: r["id"] for n, r in targets.items()} != {
            n: r["id"] for n, r in current.items()
        }:
            raise RuntimeError(
                "The running lab container set changed during verification."
            )
        for name, row in ingested.items():
            print(
                f"PASS {name} [{row['container_id'][:12]}]: CPU total={row['cpu_total_seconds']:.3f}s, memory={row['memory_usage_bytes'] / 1024**2:.2f} MiB",
                flush=True,
            )
        readiness()
    except Exception:
        subprocess.run(
            ["docker", "logs", "--tail", "35", CADVISOR], cwd=ROOT, check=False
        )
        raise
    finally:
        after = snapshot(protected)
        if after != before:
            raise RuntimeError(
                "A protected lab container changed. Inspect before continuing."
            )
        print("Protected application and monitoring containers: unchanged.", flush=True)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    evidence = ROOT / "backups" / f"container-monitoring-check-{stamp}.json"
    evidence.parent.mkdir(exist_ok=True)
    inputs = [
        "compose.infrastructure.yaml",
        "monitoring/prometheus.yml",
        "scripts/start_container_monitoring.py",
        "scripts/start_node_exporter.py",
        "scripts/verify_host_scrape.py",
        "scripts/verify_host_metrics.py",
    ]
    evidence.write_text(
        json.dumps(
            {
                "checked_at_utc": datetime.now(UTC).isoformat(),
                "result": "passed",
                "verify_only": args.verify_only,
                "source_commit": output("git", "rev-parse", "HEAD").strip(),
                "working_tree_dirty": bool(
                    output("git", "status", "--porcelain").strip()
                ),
                "cadvisor": runtime,
                "direct_metrics": direct,
                "ingested_metrics": ingested,
                "host_checks": host_result,
                "protected_before": before,
                "protected_after": after,
                "input_sha256": {
                    name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                    for name in inputs
                },
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Evidence saved: {evidence.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
