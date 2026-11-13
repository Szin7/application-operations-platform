"""Load tested monitoring rules and verify the existing lab without fault injection."""

import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from start_container_monitoring import MONITORING, running_lab
from start_node_exporter import output, readiness, snapshot
from verify_host_scrape import api, single, value

ROOT = Path(__file__).resolve().parents[1]
PROMETHEUS = "application-operations-monitoring-prometheus-1"
EXPECTED = {
    "ApiScrapeFailed": 60,
    "ReadinessCheckFailed": 60,
    "ReadinessTargetsMissing": 60,
    "InfrastructureExporterDown": 60,
    "InfrastructureTargetsMissing": 60,
    "HostCollectionFailed": 60,
    "HostCollectorsMissing": 60,
    "HostCpuBusy": 300,
    "HostMemoryLow": 300,
    "HostFilesystemLowSpace": 300,
    "ContainerMemoryHigh": 300,
}


def loaded_rules():
    deadline = time.monotonic() + 90
    while True:
        groups = api("rules", type="alert")["groups"]
        rules = [rule for group in groups for rule in group["rules"]]
        names = {rule["name"] for rule in rules}
        if (
            names == set(EXPECTED)
            and len(rules) == len(EXPECTED)
            and all(
                rule.get("health") == "ok" and not rule.get("lastError")
                for rule in rules
            )
        ):
            for rule in rules:
                if rule["duration"] != EXPECTED[rule["name"]]:
                    raise RuntimeError(f"Unexpected alert delay for {rule['name']}")
            return rules
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Alert rules did not load and evaluate cleanly: {rules}"
            )
        print("Waiting for all alert rules to evaluate successfully...", flush=True)
        time.sleep(5)


def grafana_memory():
    container_id = output(
        "docker",
        "inspect",
        "--format",
        "{{.Id}}",
        "application-operations-monitoring-grafana-1",
    ).strip()
    selector = '{job="container-resources",container_id="' + container_id + '"}'
    result = {
        "container_id": container_id,
        "usage_bytes": value(single("container_memory_usage_bytes" + selector)),
        "working_set_bytes": value(
            single("container_memory_working_set_bytes" + selector)
        ),
        "limit_bytes": value(single("container_spec_memory_limit_bytes" + selector)),
    }
    if result["limit_bytes"] <= 0 or result["working_set_bytes"] < 0:
        raise RuntimeError("Grafana memory metrics could not be validated.")
    print(
        f"Grafana memory: usage={result['usage_bytes'] / 1024**2:.2f} MiB, "
        f"working set={result['working_set_bytes'] / 1024**2:.2f} MiB, "
        f"limit={result['limit_bytes'] / 1024**2:.2f} MiB",
        flush=True,
    )
    return result


def main():
    before = running_lab()
    if PROMETHEUS not in before:
        raise RuntimeError("The existing Prometheus container must be running.")
    previous_prometheus = before.pop(PROMETHEUS)
    protected = [record["id"] for record in before.values()]
    readiness()
    subprocess.run(["bash", "scripts/check_monitoring.sh"], cwd=ROOT, check=True)
    try:
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
        subprocess.run(
            [
                "uv",
                "run",
                "--locked",
                "python",
                "scripts/start_readiness_monitoring.py",
                "--verify-only",
            ],
            cwd=ROOT,
            check=True,
        )
        rules = loaded_rules()
        memory = grafana_memory()
        for rule in rules:
            print(
                f"Rule loaded: {rule['name']} | health={rule['health']} | state={rule['state']}",
                flush=True,
            )
        active = [rule["name"] for rule in rules if rule["state"] != "inactive"]
        if active:
            print(
                "Review current pending or firing rules: " + ", ".join(active),
                flush=True,
            )
        else:
            print("All alert rules are currently inactive.", flush=True)
        readiness()
    finally:
        after = snapshot(protected)
        if after != before:
            raise RuntimeError(
                "A protected lab container changed. Inspect before continuing."
            )
        print("All existing lab containers except Prometheus: unchanged.", flush=True)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = ROOT / "backups" / f"monitoring-alerts-check-{stamp}.json"
    path.parent.mkdir(exist_ok=True)
    files = [
        "monitoring/prometheus.yml",
        "monitoring/rules/infrastructure.yml",
        "monitoring/tests/infrastructure.test.yml",
        "scripts/check_monitoring.sh",
        "scripts/enable_monitoring_alerts.py",
    ]
    path.write_text(
        json.dumps(
            {
                "checked_at_utc": datetime.now(UTC).isoformat(),
                "configuration_and_rule_checks": "passed",
                "active_rules": active,
                "rules": rules,
                "grafana_memory": memory,
                "fault_injection_performed": False,
                "source_commit": output("git", "rev-parse", "HEAD").strip(),
                "working_tree_dirty": bool(
                    output("git", "status", "--porcelain").strip()
                ),
                "prometheus_before": previous_prometheus,
                "prometheus_after": snapshot([PROMETHEUS])[PROMETHEUS],
                "protected_before": before,
                "protected_after": after,
                "input_sha256": {
                    f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest()
                    for f in files
                },
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Evidence saved: {path.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
