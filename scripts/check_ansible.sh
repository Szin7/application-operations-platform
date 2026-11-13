#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

command -v ansible-playbook >/dev/null

python3 - <<'PY'
from pathlib import Path

import yaml

for path in sorted(Path("ansible").rglob("*.yml")):
    yaml.safe_load(path.read_text())
print("Ansible YAML parsed, including task files.")
PY

for playbook in preflight deploy; do
    echo "Checking ansible/$playbook.yml syntax..."
    ansible-playbook -i ansible/inventory.yml \
        "ansible/$playbook.yml" --syntax-check
done

echo "Ansible syntax checks passed. No deployment tasks were executed."
