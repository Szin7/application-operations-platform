"""Verify that Prometheus ingests the host metrics already checked on WSL."""

import json
import math
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from verify_host_metrics import decode_mount_path
from verify_host_metrics import main as verify_direct_metrics

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = '{job="wsl-host",instance="appops-wsl",scope="wsl2"}'


def api(path, **params):
    url = f"http://127.0.0.1:9090/api/v1/{path}?{urlencode(params)}"
    with urlopen(url, timeout=10) as response:
        result = json.load(response)
    if result.get("status") != "success" or result.get("warnings"):
        raise RuntimeError(f"Prometheus API failed: {result}")
    return result["data"]


def query(expression):
    result = api("query", query=expression)
    if result["resultType"] != "vector" or not result["result"]:
        raise RuntimeError(f"No vector data for {expression}")
    return result["result"]


def value(sample):
    number = float(sample["value"][1])
    if not math.isfinite(number):
        raise RuntimeError(f"Non-finite sample: {sample}")
    return number


def single(expression):
    samples = query(expression)
    if len(samples) != 1:
        raise RuntimeError(f"Expected one series for {expression}, got {len(samples)}")
    return samples[0]


def wait_for_targets():
    expected = {
        ("application-api", "staging"),
        ("application-api", "production"),
        ("wsl-host", ""),
    }
    deadline = time.monotonic() + 90
    while True:
        targets = api("targets", state="active")["activeTargets"]
        selected = [
            t
            for t in targets
            if (t["labels"].get("job"), t["labels"].get("environment", "")) in expected
        ]
        seen = {
            (t["labels"].get("job"), t["labels"].get("environment", ""))
            for t in selected
        }
        if (
            seen == expected
            and len(selected) == 3
            and all(
                t["health"] == "up"
                and not t["lastError"]
                and 0
                <= time.time() - datetime.fromisoformat(t["lastScrape"]).timestamp()
                < 45
                for t in selected
            )
        ):
            return selected
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Expected three healthy, recently scraped targets: {selected}"
            )
        print("Waiting for fresh application and WSL host scrapes...", flush=True)
        time.sleep(5)


def verify():
    verify_direct_metrics()
    targets = wait_for_targets()
    if value(single("up" + SELECTOR)) != 1:
        raise RuntimeError("WSL target is not up.")
    collectors = query("node_scrape_collector_success" + SELECTOR)
    names = {s["metric"]["collector"] for s in collectors}
    if (
        names != {"cpu", "meminfo", "loadavg", "filesystem", "time"}
        or len(collectors) != 5
        or any(value(s) != 1 for s in collectors)
    ):
        raise RuntimeError(f"Unexpected or failed collectors: {collectors}")
    version = single("node_exporter_build_info" + SELECTOR)["metric"]["version"]
    if version != "1.12.1-wsl.1":
        raise RuntimeError(f"Unexpected exporter version: {version}")
    memory = value(single("node_memory_MemTotal_bytes" + SELECTOR))
    local_memory = next(
        int(line.split()[1]) * 1024
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.startswith("MemTotal:")
    )
    cpu_selector = SELECTOR[:-1] + ',mode="idle"}'
    cpus = value(single(f"count(node_cpu_seconds_total{cpu_selector})"))
    local_cpus = len(
        re.findall(r"^cpu\d+\s", Path("/proc/stat").read_text(), re.MULTILINE)
    )
    if memory != local_memory or cpus != local_cpus:
        raise RuntimeError("Ingested memory or CPU count differs from WSL.")
    sizes = query("node_filesystem_size_bytes" + SELECTOR)
    if len(sizes) != 2 or {s["metric"]["mountpoint"] for s in sizes} != {"/", "/mnt/d"}:
        raise RuntimeError(f"Unexpected filesystem series: {sizes}")
    for sample in sizes:
        mount = sample["metric"]["mountpoint"]
        stat = os.statvfs(mount)
        filesystem = json.loads(
            subprocess.check_output(
                ["findmnt", "--json", "--target", mount, "--output", "SOURCE,FSTYPE"],
                text=True,
                timeout=10,
            )
        )["filesystems"][0]
        if (
            value(sample) != stat.f_blocks * stat.f_frsize
            or decode_mount_path(sample["metric"]["device"]) != filesystem["source"]
            or sample["metric"]["fstype"] != filesystem["fstype"]
        ):
            raise RuntimeError(
                f"Ingested filesystem identity or capacity differs for {mount}."
            )
        selector = SELECTOR[:-1] + f',mountpoint="{mount}"' + "}"
        if value(single("node_filesystem_device_error" + selector)) != 0:
            raise RuntimeError(f"Filesystem error for {mount}.")
        available = value(single("node_filesystem_avail_bytes" + selector))
        if not 0 <= available <= value(sample):
            raise RuntimeError(f"Invalid available capacity for {mount}.")
    for target in targets:
        print(
            f"Prometheus target passed: {target['labels']['job']} {target['labels']['instance']}",
            flush=True,
        )
    print(
        f"Ingested host metrics passed: {int(cpus)} CPUs, {int(memory)} memory bytes, two filesystems.",
        flush=True,
    )
    return {
        "targets": targets,
        "collectors": collectors,
        "version": version,
        "memory_bytes": memory,
        "cpu_count": cpus,
        "filesystem_sizes": sizes,
    }


def main():
    result = verify()
    result["checked_at_utc"] = datetime.now(UTC).isoformat()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = ROOT / "backups" / f"host-scrape-check-{stamp}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Evidence saved: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
