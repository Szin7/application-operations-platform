"""Build and verify only the lab's Node Exporter, preserving other services."""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
EXPORTER = "application-operations-infrastructure-node-exporter-1"
COMPOSE = ["docker", "compose", "-f", "compose.infrastructure.yaml"]


def output(*command):
    return subprocess.check_output(command, cwd=ROOT, text=True, timeout=30)


def snapshot(ids):
    records = json.loads(output("docker", "inspect", *ids))
    return {
        item["Name"].lstrip("/"): {
            "id": item["Id"],
            "image": item["Image"],
            "started_at": item["State"]["StartedAt"],
            "running": item["State"]["Running"],
            "health": item["State"].get("Health", {}).get("Status"),
        }
        for item in records
    }


def readiness():
    for port in (8002, 8003, 8082, 8083):
        with urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=10) as response:
            if response.status != 200 or json.load(response).get("status") != "ready":
                raise RuntimeError(f"Readiness failed on port {port}")
        print(f"Readiness passed: {port}", flush=True)


def main():
    ids = output(
        "docker", "ps", "--filter", "name=application-operations-", "-q"
    ).split()
    if not ids:
        raise SystemExit("No running application lab containers found.")
    before = snapshot(ids)
    before.pop(EXPORTER, None)
    required = {
        f"application-operations-{env}-{service}-1"
        for env in ("staging", "production")
        for service in ("api", "db")
    }
    if not required.issubset(before):
        raise SystemExit(
            "Both staging and production application stacks must be running."
        )
    protected_ids = [item["id"] for item in before.values()]
    readiness()
    subprocess.run(COMPOSE + ["config", "--quiet"], cwd=ROOT, check=True)
    try:
        subprocess.run(COMPOSE + ["build", "node-exporter"], cwd=ROOT, check=True)
        subprocess.run(
            COMPOSE
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
                "node-exporter",
            ],
            cwd=ROOT,
            check=True,
        )
        version = output("docker", "exec", EXPORTER, "/bin/node_exporter", "--version")
        if "version 1.12.1-wsl.1" not in version:
            raise RuntimeError(f"Unexpected exporter version: {version}")
        print(version, flush=True)
        subprocess.run(
            ["uv", "run", "--locked", "python", "scripts/verify_host_metrics.py"],
            cwd=ROOT,
            check=True,
        )
        readiness()
    finally:
        after = snapshot(protected_ids)
        if after != before:
            raise RuntimeError(
                "An existing lab container changed; inspect before continuing."
            )
        print("Existing application and monitoring containers: unchanged.", flush=True)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    evidence = ROOT / "backups" / f"node-exporter-check-{stamp}.json"
    evidence.parent.mkdir(exist_ok=True)
    inputs = [
        ROOT / "compose.infrastructure.yaml",
        *sorted((ROOT / "deploy/node-exporter").glob("*")),
    ]
    inputs += [ROOT / "scripts/verify_host_metrics.py", Path(__file__).resolve()]
    evidence.write_text(
        json.dumps(
            {
                "checked_at_utc": stamp,
                "result": "passed",
                "source_commit": output("git", "rev-parse", "HEAD").strip(),
                "working_tree_dirty": bool(
                    output("git", "status", "--porcelain").strip()
                ),
                "exporter": snapshot([EXPORTER])[EXPORTER],
                "version": version.strip(),
                "host_metric_comparison": "passed",
                "readiness_ports": [8002, 8003, 8082, 8083],
                "protected_containers_before": before,
                "protected_containers_after": after,
                "input_sha256": {
                    str(path.relative_to(ROOT)): hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                    for path in inputs
                    if path.is_file()
                },
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Evidence saved: {evidence.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
