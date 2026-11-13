#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $# -gt 1 ]]; then
    echo "Usage: $0 [new-report-directory]" >&2
    exit 2
fi

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if [[ $# -eq 1 ]]; then
    audit_dir="$1"
    mkdir -- "$audit_dir"
else
    mkdir -p backups
    audit_dir="$(mktemp -d "$project_root/backups/dependency-audit-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"
fi

echo "Audit evidence directory: $audit_dir"
date -u +%Y-%m-%dT%H:%M:%SZ > "$audit_dir/started-at-utc.txt"
git rev-parse HEAD > "$audit_dir/source-commit.txt"
sha256sum pyproject.toml uv.lock > "$audit_dir/lockfile.sha256"
if [[ -z "$(git status --porcelain)" ]]; then
    echo clean > "$audit_dir/working-tree-state.txt"
else
    echo modified > "$audit_dir/working-tree-state.txt"
fi

echo "Exporting locked runtime and development dependencies..."
uv export --locked --all-groups --no-emit-project \
    --format requirements.txt \
    --output-file "$audit_dir/requirements.txt" >/dev/null

audit=(uv tool run --python 3.14 --from pip-audit==2.10.1 pip-audit)
"${audit[@]}" --version | tee "$audit_dir/scanner-version.txt"

echo "Checking known Python dependency vulnerabilities..."
audit_status=0
"${audit[@]}" \
    --requirement "$audit_dir/requirements.txt" \
    --require-hashes --disable-pip --strict \
    --vulnerability-service pypi --progress-spinner off --timeout 30 \
    --format json --output "$audit_dir/audit.json" || audit_status=$?
printf '%s\n' "$audit_status" > "$audit_dir/scanner-exit-code.txt"

if [[ "$audit_status" -ne 0 ]]; then
    echo "Dependency audit failed (exit $audit_status). Inspect $audit_dir." >&2
    exit "$audit_status"
fi

python3 - "$audit_dir/audit.json" <<'PY'
import json
from pathlib import Path
import sys

report = json.loads(Path(sys.argv[1]).read_text())
dependencies = report.get("dependencies")
if not isinstance(dependencies, list) or not dependencies:
    raise SystemExit("Audit failed: no dependency results were returned.")
for dependency in dependencies:
    if not isinstance(dependency, dict) or "skip_reason" in dependency:
        raise SystemExit("Audit failed: a dependency was skipped or malformed.")
    if not dependency.get("name") or not dependency.get("version"):
        raise SystemExit("Audit failed: a dependency has no name or version.")
    vulnerabilities = dependency.get("vulns")
    if not isinstance(vulnerabilities, list) or vulnerabilities:
        raise SystemExit("Audit failed: vulnerability results are missing or nonempty.")
print(f"Audited Python packages: {len(dependencies)}")
print("Skipped packages: 0")
print("Known vulnerabilities: 0")
PY

echo "Dependency audit passed. Evidence saved: $audit_dir"
