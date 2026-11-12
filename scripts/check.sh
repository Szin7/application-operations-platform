#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

echo "Installing locked dependencies..."
uv sync --locked

echo "Checking Python code..."
uv run --locked ruff check app tests migrations scripts
uv run --locked ruff format --check app tests migrations scripts

echo "Checking shell scripts..."
for script in scripts/*.sh; do
    bash -n "$script"
done

echo "Running unit tests..."
RUN_DB_TESTS=0 uv run --locked python -m pytest -v

echo "Code checks passed."
