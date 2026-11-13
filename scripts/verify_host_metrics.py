"""Compare Node Exporter's mounted view with the local WSL environment."""

import json
import os
import re
import subprocess
from pathlib import Path
from urllib.request import urlopen

from prometheus_client.parser import text_string_to_metric_families


def decode_mount_path(value):
    """Decode mountinfo octal escapes once, including Windows backslashes."""
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)


def main():
    with urlopen("http://127.0.0.1:9100/metrics", timeout=15) as response:
        if response.status != 200:
            raise SystemExit("Node Exporter did not return HTTP 200.")
        text = response.read().decode()
    samples = [
        sample
        for family in text_string_to_metric_families(text)
        for sample in family.samples
    ]

    def metric(name, **labels):
        matches = [
            sample
            for sample in samples
            if sample.name == name
            and all(sample.labels.get(key) == value for key, value in labels.items())
        ]
        if len(matches) != 1:
            raise SystemExit(
                f"Expected one {name} sample for {labels}; received {len(matches)}."
            )
        return matches[0]

    for collector in ("cpu", "meminfo", "loadavg", "filesystem", "time"):
        if metric("node_scrape_collector_success", collector=collector).value != 1:
            raise SystemExit(f"Collector failed: {collector}. Check exporter logs.")
    print("Enabled collectors: passed")

    local_memory = next(
        int(line.split()[1]) * 1024
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.startswith("MemTotal:")
    )
    exported_memory = int(metric("node_memory_MemTotal_bytes").value)
    print(f"Memory bytes: WSL={local_memory}, exporter={exported_memory}")
    if exported_memory != local_memory:
        raise SystemExit(
            "Memory views differ. Resolve the host scope before proceeding."
        )

    local_cpus = len(
        re.findall(r"^cpu\d+\s", Path("/proc/stat").read_text(), re.MULTILINE)
    )
    exported_cpus = {
        sample.labels["cpu"]
        for sample in samples
        if sample.name == "node_cpu_seconds_total"
        and sample.labels.get("mode") == "idle"
    }
    print(f"Logical CPUs: WSL={local_cpus}, exporter={len(exported_cpus)}")
    if len(exported_cpus) != local_cpus:
        raise SystemExit("CPU views differ. Resolve the host scope before proceeding.")

    for mountpoint in ("/", "/mnt/d"):
        filesystem = json.loads(
            subprocess.check_output(
                [
                    "findmnt",
                    "--json",
                    "--target",
                    mountpoint,
                    "--output",
                    "SOURCE,FSTYPE,TARGET",
                ],
                text=True,
                timeout=10,
            )
        )["filesystems"][0]
        size = metric("node_filesystem_size_bytes", mountpoint=mountpoint)
        available = metric("node_filesystem_avail_bytes", mountpoint=mountpoint)
        stats = os.statvfs(mountpoint)
        local_size = stats.f_blocks * stats.f_frsize
        print(
            f"Filesystem {mountpoint}: "
            f"WSL={filesystem['source']} ({filesystem['fstype']}), "
            f"exporter={size.labels.get('device')} ({size.labels.get('fstype')})"
        )
        print(f"  Size bytes: WSL={local_size}, exporter={int(size.value)}")
        print(f"  Exported available GiB: {available.value / 1024**3:.2f}")
        if (
            decode_mount_path(size.labels.get("device", "")) != filesystem["source"]
            or size.labels.get("fstype") != filesystem["fstype"]
        ):
            raise SystemExit(f"Filesystem identity differs for {mountpoint}.")
        if int(size.value) != local_size:
            raise SystemExit(f"Filesystem capacity differs for {mountpoint}.")
        if metric("node_filesystem_device_error", mountpoint=mountpoint).value != 0:
            raise SystemExit(f"Filesystem collection error for {mountpoint}.")

    print("Host metrics matched the WSL view, including the mounted D: filesystem.")
    print(
        "The WSL root capacity is virtual; /mnt/d reports Windows D: volume capacity."
    )


if __name__ == "__main__":
    main()
