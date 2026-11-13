# Node Exporter on WSL

The official Node Exporter 1.12.1 image started successfully in this lab,
but its filesystem collector failed. WSL exposed a raw space in the 9p
mount options for `C:\Program Files\Docker`. The procfs 0.21.1 parser
expected the separator at a fixed position and rejected the complete
mount table before filesystem filters ran.

This local image builds Node Exporter 1.12.1 with the released procfs
0.23.0 fix. It is labelled `1.12.1-wsl.1` to distinguish it from the
official image. Go module and checksum files lock the resolved dependencies;
the builder and runtime base images are pinned by digest.

The `nonvme` build tag omits the physical NVMe collector: its old API is
incompatible with procfs 0.23.0, and this lab does not use it. CPU, memory,
load average, time, and filesystem collection remain enabled. This image
is specific to the WSL lab, not a general replacement for Node Exporter.

The build runs a regression test containing the failing WSL mount format,
checks that malformed input still fails, and runs the upstream filesystem
tests. Build details, source metadata, dependency files, and upstream
license notices are retained at `/usr/share/node-exporter-build/`.

The runtime remains non-root, with read-only mounts, dropped capabilities,
and the existing resource limits. Building successfully does not prove
host visibility: run `scripts/verify_host_metrics.py` on WSL before adding
the exporter to Prometheus.

The verifier decodes mountinfo octal escapes when comparing device labels
with `findmnt`. For example, `D:\134` and `D:\` identify the same drive.
The root filesystem capacity is the WSL virtual filesystem capacity;
`/mnt/d` reports the mounted Windows D: volume. Neither represents the
whole laptop's free disk space.

Upstream references:

- https://github.com/prometheus/procfs/pull/874
- https://github.com/prometheus/procfs/releases/tag/v0.23.0
- https://github.com/prometheus/node_exporter/blob/v1.12.1/go.mod

Revisit this local build when an official Node Exporter release includes
the fix. Replace it only after the same mount regression and live host
comparisons pass.

## Verified host collection

On 13 November 2026, the local image built and all five enabled collectors
passed. Exported memory matched WSL at 8,243,068,928 bytes, and all 12
logical CPUs were present. Filesystem identities and capacities matched
for `/` (ext4, `/dev/sdf`) and `/mnt/d` (9p, Windows D:).

All four direct and proxied application readiness checks passed. Existing
application and monitoring containers were unchanged. Local evidence:
`backups/node-exporter-check-20261113T065751619929Z.json`.

Prometheus uses job `wsl-host`, instance `appops-wsl`, and scope `wsl2`.
Run `uv run --locked python scripts/verify_host_scrape.py` after loading
the configuration to check target health and the ingested metrics.
These labels describe the WSL Linux view, not whole-Windows CPU or memory.
