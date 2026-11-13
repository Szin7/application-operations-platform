"""Verify local firing and recovery delivery with two bounded container outages."""

import hashlib
import json
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

from enable_monitoring_alerts import loaded_rules
from start_container_monitoring import running_lab
from start_node_exporter import output, readiness, snapshot
from verify_host_scrape import api

ROOT = Path(__file__).resolve().parents[1]
RECEIVER = "http://127.0.0.1:9095/events"
DRILLS = (
    {
        "container": "application-operations-proxy-staging-1",
        "labels": {
            "alertname": "ReadinessCheckFailed",
            "environment": "staging",
            "route": "proxy",
            "job": "application-readiness",
            "instance": "http://application-operations-proxy-staging-1:8080/health/ready",
        },
        "protected_ports": (8002, 8003, 8083),
    },
    {
        "container": "application-operations-infrastructure-node-exporter-1",
        "labels": {
            "alertname": "InfrastructureExporterDown",
            "job": "wsl-host",
            "instance": "appops-wsl",
        },
        "protected_ports": (8002, 8003, 8082, 8083),
    },
)


def now():
    return datetime.now(UTC).isoformat()


def timestamp(value):
    return datetime.fromisoformat(value)


def read_json(url):
    with urlopen(url, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"Unexpected HTTP status at {url}")
        return json.load(response)


def labels_match(actual, expected):
    return all(actual.get(key) == value for key, value in expected.items())


def match_notification(events, seen, labels, status, since, firing=None):
    """Require a new individual alert; the group's status alone is insufficient."""
    for event in events:
        if event["id"] in seen or timestamp(event["received_at"]) < timestamp(since):
            continue
        for alert in event["notification"]["alerts"]:
            if alert.get("status") != status or not labels_match(
                alert.get("labels", {}), labels
            ):
                continue
            if not alert.get("fingerprint") or not alert.get("startsAt"):
                continue
            if firing is None:
                if timestamp(alert["startsAt"]) < timestamp(since):
                    continue
            elif (
                alert["fingerprint"] != firing["fingerprint"]
                or alert["startsAt"] != firing["startsAt"]
                or alert["labels"] != firing["labels"]
                or timestamp(alert["endsAt"]) <= timestamp(alert["startsAt"])
            ):
                continue
            return {"event": event, "alert": alert}
    return None


def active_alerts(labels):
    return [
        alert
        for alert in api("alerts")["alerts"]
        if labels_match(alert["labels"], labels)
    ]


def protect(before, ports, ticket):
    after = snapshot([record["id"] for record in before.values()])
    if after != before:
        raise RuntimeError("A protected container changed during the drill.")
    for port in ports:
        if read_json(f"http://127.0.0.1:{port}/health/ready") != {"status": "ready"}:
            raise RuntimeError(f"Protected readiness failed on port {port}")
    for port in (8003, 8083):
        if read_json(f"http://127.0.0.1:{port}/tickets/{ticket['id']}") != ticket:
            raise RuntimeError("The original production ticket no longer matches.")
    return after


def wait_for(description, check, guard, timeout=240):
    deadline = time.monotonic() + timeout
    next_report = 0
    while True:
        guard()
        result = check()
        if result:
            print(f"PASS: {description}", flush=True)
            return result
        current = time.monotonic()
        if current >= deadline:
            raise RuntimeError(f"Timed out waiting for {description}")
        if current >= next_report:
            print(f"Waiting: {description}", flush=True)
            next_report = current + 15
        time.sleep(5)


def restore_container(name, original):
    # Use the original ID so a concurrent replacement cannot become our target.
    output("docker", "start", original["id"])

    def healthy():
        current = snapshot([original["id"]])[name]
        if current["id"] != original["id"] or current["image"] != original["image"]:
            raise RuntimeError(f"Container identity changed: {name}")
        return (
            current if current["running"] and current["health"] == "healthy" else None
        )

    return wait_for(f"{name} restored and healthy", healthy, lambda: None, timeout=120)


def run_drill(spec, ticket, record, save):
    before = running_lab()
    name, labels = spec["container"], spec["labels"]
    original = before.pop(name)
    if not original["running"] or original["health"] != "healthy":
        raise RuntimeError(f"Drill target is not healthy: {name}")

    def guard():
        return protect(before, spec["protected_ports"], ticket)

    guard()
    if active_alerts(labels):
        raise RuntimeError("The selected alert is already pending or firing.")
    seen = {event["id"] for event in read_json(RECEIVER)}
    record.update(
        container=name,
        labels=labels,
        before=original,
        started_at_utc=now(),
        status="running",
        protected_before=before,
    )
    save()

    def delivered(status, since, firing=None):
        alerts = active_alerts(labels)
        if status == "firing" and not any(a["state"] == "firing" for a in alerts):
            return None
        if status == "resolved" and alerts:
            return None
        return match_notification(
            read_json(RECEIVER), seen, labels, status, since, firing
        )

    print(f"Stopping only {name} for the delivery check...", flush=True)
    try:
        # Enter the cleanup scope before stopping: even a stop timeout needs recovery.
        output("docker", "stop", "--time", "10", original["id"])
        stopped = snapshot([original["id"]])[name]
        if stopped["running"]:
            raise RuntimeError(f"The drill target did not stop: {name}")
        record["stopped"] = stopped
        save()
        record["firing"] = wait_for(
            f"{labels['alertname']} firing notification",
            lambda: delivered("firing", record["started_at_utc"]),
            guard,
        )
        save()
    finally:
        record["restore_requested_at_utc"] = now()
        # Restore before saving or checking any other service.
        record["restored"] = restore_container(name, original)
        save()

    record["resolved"] = wait_for(
        f"{labels['alertname']} resolved notification",
        lambda: delivered(
            "resolved", record["restore_requested_at_utc"], record["firing"]["alert"]
        ),
        guard,
    )
    after = guard()
    readiness()
    record.update(status="passed", finished_at_utc=now(), protected_after=after)
    save()
    print(f"Firing and recovery delivery passed: {name}", flush=True)


def main():
    # SIGINT already raises KeyboardInterrupt. Make SIGTERM use the same cleanup path.
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"Received signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
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
    if any(rule["state"] != "inactive" for rule in loaded_rules()):
        raise RuntimeError(
            "Review existing pending or firing alerts before this drill."
        )
    ticket = json.loads((ROOT / "backups/rollback-check.json").read_text())["ticket"]
    if type(ticket.get("id")) is not int or ticket["id"] <= 0:
        raise RuntimeError("The original production ticket record is invalid.")
    before = running_lab()
    targets = {spec["container"] for spec in DRILLS}
    if not targets.issubset(before):
        raise RuntimeError("Both drill containers must already be running.")
    protect(before, (8002, 8003, 8082, 8083), ticket)
    read_json(RECEIVER)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = ROOT / "backups" / f"alert-delivery-check-{stamp}.json"
    evidence = {
        "started_at_utc": now(),
        "status": "running",
        "drills": [],
        "source_commit": output("git", "rev-parse", "HEAD").strip(),
        "working_tree_dirty": bool(output("git", "status", "--porcelain").strip()),
        "input_sha256": {
            rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
            for rel in (
                "scripts/check_alert_delivery.py",
                "monitoring/prometheus.yml",
                "monitoring/rules/infrastructure.yml",
                "monitoring/alertmanager.yml",
            )
        },
    }

    def save():
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(evidence, indent=2) + "\n")
        temporary.replace(path)

    save()
    print(f"Evidence file: {path.relative_to(ROOT)}", flush=True)
    try:
        for spec in DRILLS:
            record = {}
            evidence["drills"].append(record)
            run_drill(spec, ticket, record, save)
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
        protected = {name: data for name, data in before.items() if name not in targets}
        protect(protected, (8002, 8003, 8082, 8083), ticket)
        after = running_lab()
        if set(after) != set(before):
            raise RuntimeError("The running lab container inventory changed.")
        for name in targets:
            if any(after[name][key] != before[name][key] for key in ("id", "image")):
                raise RuntimeError(f"A drill container was replaced: {name}")
        evidence.update(
            status="passed",
            containers_before=before,
            containers_after=after,
            original_production_ticket="matched before, during, and after drills",
        )
    except BaseException as error:
        evidence.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        evidence["finished_at_utc"] = now()
        save()
        print(
            f"Evidence saved ({evidence['status']}): {path.relative_to(ROOT)}",
            flush=True,
        )
    print(
        "Both delivery checks passed; production stayed ready and its ticket matched.",
        flush=True,
    )


if __name__ == "__main__":
    main()
