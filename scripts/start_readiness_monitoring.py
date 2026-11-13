"""Install and verify direct and proxied HTTP readiness probes."""

import argparse
import hashlib
import json
import math
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from prometheus_client.parser import text_string_to_metric_families
from start_container_monitoring import INFRA, MONITORING, running_lab
from start_node_exporter import output, readiness, snapshot
from verify_host_scrape import query, single, value

ROOT = Path(__file__).resolve().parents[1]
EXPORTER = "application-operations-infrastructure-blackbox-exporter-1"
PROMETHEUS = "application-operations-monitoring-prometheus-1"
IMAGE = "quay.io/prometheus/blackbox-exporter@sha256:ea1c7aa3ef3f307cd03e85f34abb604478ccb90b567fc690da0cd9776da76b13"
TARGETS = {
    (env, route): f"http://application-operations-{env}-api-1:8000/health/ready"
    if route == "direct"
    else f"http://application-operations-proxy-{env}-1:8080/health/ready"
    for env in ("staging", "production")
    for route in ("direct", "proxy")
}
FIXTURE = """
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status = {"/ready": 200, "/wrong-body": 200, "/error": 503, "/redirect": 302}.get(self.path, 404)
        body = b'{"status":"not_ready"}' if self.path == "/wrong-body" else b'{"status":"ready"}'
        self.send_response(status)
        if self.path == "/redirect":
            self.send_header("Location", "/ready")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass
HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
"""


def probe(target):
    url = "http://127.0.0.1:9115/probe?" + urlencode(
        {"module": "http_readiness", "target": target}
    )
    text = output("docker", "exec", EXPORTER, "wget", "-q", "-T", "7", "-O", "-", url)
    wanted = {"probe_success", "probe_http_status_code", "probe_duration_seconds"}
    result = {
        s.name: s.value
        for f in text_string_to_metric_families(text)
        for s in f.samples
        if s.name in wanted
    }
    if set(result) != wanted or not all(math.isfinite(v) for v in result.values()):
        raise RuntimeError(f"Incomplete probe result for {target}: {result}")
    return result


def check_probe_contract():
    # Reuse the immutable image ID of the existing Python alert receiver.
    image = output(
        "docker",
        "inspect",
        "--format",
        "{{.Image}}",
        "application-operations-monitoring-alert-receiver-1",
    ).strip()
    name = "appops-readiness-check-" + uuid.uuid4().hex[:12]
    container = output(
        "docker",
        "run",
        "-d",
        "--pull",
        "never",
        "--name",
        name,
        "--network",
        "application-operations-monitoring_default",
        "--user",
        "10001:10001",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--memory",
        "64m",
        "--cpus",
        "0.25",
        "--pids-limit",
        "64",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        image,
        "python",
        "-u",
        "-c",
        FIXTURE,
    ).strip()
    results = {}
    try:
        deadline = time.monotonic() + 30
        while probe(f"http://{name}:8080/ready")["probe_success"] != 1:
            if time.monotonic() >= deadline:
                raise RuntimeError("Temporary readiness fixture did not become ready.")
            time.sleep(2)
        for path, success, status in [
            ("ready", 1, 200),
            ("wrong-body", 0, 200),
            ("error", 0, 503),
            ("redirect", 0, 302),
        ]:
            result = probe(f"http://{name}:8080/{path}")
            if (
                result["probe_success"] != success
                or result["probe_http_status_code"] != status
            ):
                raise RuntimeError(f"Probe contract failed for {path}: {result}")
            results[path] = result
            print(
                f"Probe contract passed: {path}, HTTP {status}, success={success}",
                flush=True,
            )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container], check=True, stdout=subprocess.DEVNULL
        )
    return {"fixture_image": image, "results": results}


def verify_scrapes():
    if value(single('up{job="readiness-exporter",instance="appops-prober"}')) != 1:
        raise RuntimeError("Readiness exporter scrape is not up.")
    rows = {}
    for metric in (
        "up",
        "probe_success",
        "probe_http_status_code",
        "probe_duration_seconds",
    ):
        samples = query(metric + '{job="application-readiness"}')
        seen = set()
        for sample in samples:
            labels = sample["metric"]
            key = (labels.get("environment"), labels.get("route"))
            if (
                key not in TARGETS
                or key in seen
                or labels.get("instance") != TARGETS[key]
            ):
                raise RuntimeError(f"Unexpected readiness series: {labels}")
            seen.add(key)
            number = value(sample)
            expected = {"up": 1, "probe_success": 1, "probe_http_status_code": 200}
            if (metric in expected and number != expected[metric]) or number < 0:
                raise RuntimeError(f"Readiness failed for {key}: {metric}={number}")
            rows.setdefault("/".join(key), {})[metric] = number
        if seen != set(TARGETS):
            raise RuntimeError(f"Missing readiness series for {metric}")
    ages = query('time() - timestamp(probe_success{job="application-readiness"})')
    fresh = set()
    for sample in ages:
        labels = sample["metric"]
        key = (labels.get("environment"), labels.get("route"))
        if key not in TARGETS or key in fresh or not 0 <= value(sample) < 45:
            raise RuntimeError("Stale or unexpected readiness samples.")
        fresh.add(key)
    if fresh != set(TARGETS):
        raise RuntimeError("Missing readiness sample timestamps.")
    return rows


def check_runtime():
    details = json.loads(output("docker", "inspect", EXPORTER))[0]
    host = details["HostConfig"]
    mounts = details["Mounts"]
    if (
        details["Config"]["Image"] != IMAGE
        or details["Config"]["User"] != "65534:65534"
        or host["Privileged"]
        or not host["ReadonlyRootfs"]
        or host.get("CapAdd")
        or "ALL" not in (host.get("CapDrop") or [])
        or "no-new-privileges:true" not in (host.get("SecurityOpt") or [])
        or host["Memory"] != 64 * 1024**2
        or host["NanoCpus"] != 250_000_000
        or host["PidsLimit"] != 64
        or len(mounts) != 1
        or mounts[0]["RW"]
        or mounts[0]["Destination"] != "/etc/blackbox_exporter/config.yml"
        or any(details["NetworkSettings"]["Ports"].values())
        or set(details["NetworkSettings"]["Networks"])
        != {
            "application-operations-monitoring_default",
            "application-operations-staging_default",
            "application-operations-production_default",
        }
    ):
        raise RuntimeError("Readiness exporter runtime restrictions differ.")
    print(
        "Readiness exporter runtime restrictions and network scope: passed", flush=True
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Check existing probes without starting, recreating, or testing with temporary containers",
    )
    args = parser.parse_args()
    before = running_lab()
    if not args.verify_only:
        before.pop(EXPORTER, None)
        before.pop(PROMETHEUS, None)
    protected = [r["id"] for r in before.values()]
    readiness()
    contract = None
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
                    "--force-recreate",
                    "--pull",
                    "never",
                    "--wait",
                    "--wait-timeout",
                    "90",
                    "blackbox-exporter",
                ],
                cwd=ROOT,
                check=True,
            )
        check_runtime()
        if not args.verify_only:
            contract = check_probe_contract()
        direct = {}
        for key, target in TARGETS.items():
            result = probe(target)
            if result["probe_success"] != 1 or result["probe_http_status_code"] != 200:
                raise RuntimeError(f"Live readiness probe failed: {key}: {result}")
            direct["/".join(key)] = result
            print(f"Direct probe passed: {'/'.join(key)}", flush=True)
        if not args.verify_only:
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
        deadline = time.monotonic() + 90
        while True:
            try:
                scrapes = verify_scrapes()
                break
            except RuntimeError as exc:
                if time.monotonic() >= deadline:
                    raise
                print(f"Waiting for readiness scrapes: {exc}", flush=True)
                time.sleep(5)
        print("Prometheus readiness checks: four fresh probes passed.", flush=True)
        subprocess.run(
            [
                "uv",
                "run",
                "--locked",
                "python",
                "scripts/start_container_monitoring.py",
                "--verify-only",
            ],
            cwd=ROOT,
            check=True,
        )
        readiness()
    except Exception:
        subprocess.run(
            ["docker", "logs", "--tail", "35", EXPORTER], cwd=ROOT, check=False
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
    path = ROOT / "backups" / f"readiness-monitoring-check-{stamp}.json"
    path.parent.mkdir(exist_ok=True)
    files = [
        "compose.infrastructure.yaml",
        "monitoring/blackbox.yml",
        "monitoring/prometheus.yml",
        "scripts/start_readiness_monitoring.py",
        "scripts/check_monitoring.sh",
    ]
    path.write_text(
        json.dumps(
            {
                "checked_at_utc": datetime.now(UTC).isoformat(),
                "result": "passed",
                "verify_only": args.verify_only,
                "source_commit": output("git", "rev-parse", "HEAD").strip(),
                "working_tree_dirty": bool(
                    output("git", "status", "--porcelain").strip()
                ),
                "probe_contract": contract,
                "direct_probes": direct,
                "prometheus_probes": scrapes,
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
