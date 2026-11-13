"""Check dashboard structure, mounted JSON, and live Prometheus query results."""

import argparse
import hashlib
import json
import math
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from start_container_monitoring import running_lab
from start_node_exporter import output, snapshot
from verify_host_scrape import api, single, value

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = "monitoring/grafana/dashboards/infrastructure.json"
GRAFANA = "application-operations-monitoring-grafana-1"


def read_dashboard():
    document = json.loads((ROOT / RELATIVE).read_text())
    spec = document["spec"]
    if (
        document["metadata"]["name"] != "appops-infrastructure"
        or spec["uid"] != "appops-infrastructure"
    ):
        raise RuntimeError("Unexpected dashboard identity.")
    panels = spec["panels"]
    if len(panels) != 10 or len({p["id"] for p in panels}) != 10:
        raise RuntimeError("Expected ten uniquely identified panels.")
    for index, panel in enumerate(panels):
        box = panel["gridPos"]
        if not (
            0 <= box["x"] < 24
            and box["w"] > 0
            and box["x"] + box["w"] <= 24
            and box["y"] >= 0
            and box["h"] > 0
        ):
            raise RuntimeError(f"Invalid panel position: {panel['title']}")
        for other in panels[index + 1 :]:
            b = other["gridPos"]
            if (
                box["x"] < b["x"] + b["w"]
                and b["x"] < box["x"] + box["w"]
                and box["y"] < b["y"] + b["h"]
                and b["y"] < box["y"] + box["h"]
            ):
                raise RuntimeError("Dashboard panels overlap.")
        if panel["datasource"]["uid"] != "prometheus":
            raise RuntimeError("Unexpected dashboard data source.")
    return document


def expression(panel, environment=".*"):
    return panel["targets"][0]["expr"].replace("${environment:regex}", environment)


def check_queries(panels, before):
    expected_ids = {record["id"] for record in before.values()}
    memory_total = value(single('node_memory_MemTotal_bytes{job="wsl-host"}'))
    limits = output(
        "docker",
        "inspect",
        "--format",
        "{{.Id}} {{.HostConfig.Memory}}",
        *sorted(expected_ids),
    )
    limited_ids = {
        row.split()[0]
        for row in limits.splitlines()
        if 0 < int(row.split()[1]) < memory_total
    }
    checked = []
    for panel in panels:
        expr = expression(panel)
        result = api("query", query=expr)
        if result["resultType"] != "vector" or not result["result"]:
            raise RuntimeError(f"No current data for {panel['title']}")
        samples = result["result"]
        if any(not math.isfinite(float(s["value"][1])) for s in samples):
            raise RuntimeError(f"Non-finite data for {panel['title']}")
        panel_id = panel["id"]
        if panel_id in (1, 3):
            routes = {
                (s["metric"]["environment"], s["metric"]["route"]) for s in samples
            }
            if (
                routes
                != {
                    (env, route)
                    for env in ("staging", "production")
                    for route in ("direct", "proxy")
                }
                or len(samples) != 4
                or any(float(s["value"][1]) != 1 for s in samples)
            ):
                raise RuntimeError("Expected four currently ready routes.")
        elif panel_id == 2:
            if (
                {s["metric"]["job"] for s in samples}
                != {"wsl-host", "container-resources", "readiness-exporter"}
                or len(samples) != 3
                or any(float(s["value"][1]) != 1 for s in samples)
            ):
                raise RuntimeError("Expected three healthy exporters.")
        elif panel_id in (4, 5) and len(samples) != 1:
            raise RuntimeError("Expected one WSL host series.")
        elif panel_id in (6, 7):
            if {s["metric"]["mountpoint"] for s in samples} != {"/", "/mnt/d"} or len(
                samples
            ) != 2:
                raise RuntimeError("Expected WSL root and D: filesystem series.")
        elif panel_id in (8, 9, 10):
            actual = {s["metric"]["container_id"] for s in samples}
            expected = limited_ids if panel_id == 10 else expected_ids
            if actual & expected_ids != expected:
                raise RuntimeError(f"Container coverage differs in {panel['title']}")
        print(f"PASS: {panel['title']} ({len(samples)} series)", flush=True)
        checked.append(
            {"panel": panel["title"], "expression": expr, "samples": samples}
        )
    for environment in ("staging", "production"):
        samples = api("query", query=expression(panels[0], environment))["result"]
        if len(samples) != 2 or any(
            s["metric"]["environment"] != environment for s in samples
        ):
            raise RuntimeError(f"Readiness filter failed: {environment}")
    print("PASS: staging and production readiness filters", flush=True)
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--emit-rules",
        action="store_true",
        help="Print recording rules for promtool query syntax checks; no service access.",
    )
    args = parser.parse_args()
    document = read_dashboard()
    panels = document["spec"]["panels"]
    if args.emit_rules:
        print(
            json.dumps(
                {
                    "groups": [
                        {
                            "name": "dashboard-validation",
                            "rules": [
                                {
                                    "record": f"dashboard_check:panel_{p['id']}",
                                    "expr": expression(p),
                                }
                                for p in panels
                            ],
                        }
                    ]
                }
            )
        )
        return
    before = running_lab()
    if GRAFANA not in before:
        raise RuntimeError("The existing Grafana container must be running.")
    try:
        mounted = json.loads(
            output(
                "docker",
                "exec",
                GRAFANA,
                "cat",
                "/etc/grafana/dashboards/infrastructure.json",
            )
        )
        if mounted != document:
            raise RuntimeError(
                "The mounted dashboard differs from the repository file."
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
        deadline = time.monotonic() + 120
        while True:
            try:
                results = check_queries(panels, before)
                break
            except RuntimeError as error:
                if time.monotonic() >= deadline:
                    raise
                print(f"Waiting for dashboard data: {error}", flush=True)
                time.sleep(10)
    finally:
        after = snapshot([record["id"] for record in before.values()])
        if after != before:
            raise RuntimeError("A lab container changed during dashboard checks.")
        print("All existing lab containers: unchanged.", flush=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = ROOT / "backups" / f"infrastructure-dashboard-check-{stamp}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "checked_at_utc": datetime.now(UTC).isoformat(),
                "mounted_dashboard": "matched",
                "dashboard_sha256": hashlib.sha256(
                    (ROOT / RELATIVE).read_bytes()
                ).hexdigest(),
                "queries": results,
                "containers": before,
                "grafana_browser_verification": "pending",
                "source_commit": output("git", "rev-parse", "HEAD").strip(),
                "working_tree_dirty": bool(
                    output("git", "status", "--porcelain").strip()
                ),
            },
            indent=2,
        )
        + "\n"
    )
    print("Container legend map:", flush=True)
    for name, data in sorted(before.items()):
        print(f"  {data['id'][:12]}  {name}", flush=True)
    print(f"Evidence saved: {path.relative_to(ROOT)}", flush=True)
    print(
        "Mounted file and Prometheus queries passed. Open Grafana to verify provisioning and display.",
        flush=True,
    )


if __name__ == "__main__":
    main()
