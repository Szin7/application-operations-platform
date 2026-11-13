import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def audit_project(tmp_path):
    root = tmp_path / "project"
    (root / "scripts").mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / "scripts/check_dependencies.sh"
    shutil.copy2(source, root / "scripts/check_dependencies.sh")
    (root / "pyproject.toml").write_text("# Test fixture\n")
    (root / "uv.lock").write_text("# Test fixture\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Audit Test",
            "-c",
            "user.email=audit-test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "--allow-empty",
            "-m",
            "Test fixture",
        ],
        check=True,
    )

    binaries = tmp_path / "bin"
    binaries.mkdir()
    uv = binaries / "uv"
    uv.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "if args[0] == 'export':\n"
        "    if os.environ.get('EXPORT_FAIL'): raise SystemExit(12)\n"
        "    pathlib.Path(args[args.index('--output-file') + 1]).write_text('demo==1.0\\n')\n"
        "elif args[-1] == '--version':\n"
        "    print('pip-audit test fixture')\n"
        "else:\n"
        "    text = os.environ['AUDIT_REPORT']\n"
        "    if text:\n"
        "        pathlib.Path(args[args.index('--output') + 1]).write_text(text)\n"
        "    raise SystemExit(int(os.environ['AUDIT_EXIT']))\n"
    )
    uv.chmod(0o755)

    def run(report, exit_code=0, **extra_env):
        environment = (
            os.environ
            | {
                "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
                "AUDIT_REPORT": report
                if isinstance(report, str)
                else json.dumps(report),
                "AUDIT_EXIT": str(exit_code),
            }
            | extra_env
        )
        output = root / "report"
        result = subprocess.run(
            ["bash", str(root / "scripts/check_dependencies.sh"), str(output)],
            check=False,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result, output

    return run


def clean_report():
    return {"dependencies": [{"name": "demo", "version": "1.0", "vulns": []}]}


def test_dependency_audit_accepts_a_complete_clean_report(audit_project):
    result, output = audit_project(clean_report())
    assert result.returncode == 0
    assert "Audited Python packages: 1" in result.stdout
    assert (output / "scanner-exit-code.txt").read_text().strip() == "0"
    assert (output / "lockfile.sha256").is_file()


@pytest.mark.parametrize("exit_code", [1, 2])
def test_dependency_audit_preserves_scanner_failure(audit_project, exit_code):
    # Even a clean-looking report cannot override a failed scanner process.
    result, output = audit_project(clean_report(), exit_code)
    assert result.returncode == exit_code
    assert "Dependency audit passed" not in result.stdout
    assert (output / "scanner-exit-code.txt").read_text().strip() == str(exit_code)


@pytest.mark.parametrize(
    "report",
    [
        {"dependencies": []},
        {"dependencies": [{"name": "demo", "skip_reason": "Unavailable"}]},
        {"dependencies": [{"name": "demo", "version": "1.0"}]},
        {
            "dependencies": [
                {"name": "demo", "version": "1.0", "vulns": [{"id": "TEST-ADVISORY"}]}
            ]
        },
        "not JSON",
    ],
    ids=["empty", "skipped", "incomplete", "vulnerable", "invalid-json"],
)
def test_dependency_audit_rejects_invalid_success_reports(audit_project, report):
    result, _ = audit_project(report)
    assert result.returncode != 0
    assert "Dependency audit passed" not in result.stdout


def test_dependency_audit_stops_when_lock_export_fails(audit_project):
    result, output = audit_project(clean_report(), EXPORT_FAIL="1")
    assert result.returncode == 12
    assert not (output / "scanner-exit-code.txt").exists()
    assert "Dependency audit passed" not in result.stdout
