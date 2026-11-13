# Python dependency checks

The dependency check audits the versions recorded in `uv.lock` against
PyPI's known-vulnerability data. It covers runtime and development dependency
groups for the Linux/Python 3.14 environment running the check.

The check was added after the Ansible deployment rehearsals. It does not
upgrade dependencies, modify the lockfile, or deploy an application image.

## Run locally

From the repository root, with uv and Python 3.14 available:

```bash
./scripts/check_dependencies.sh
```

The script exports the existing lockfile with hashes, then runs
`pip-audit==2.10.1` through an isolated uv tool environment. The project
itself is excluded from the export. `--disable-pip` avoids pip dependency
resolution; the exported locked requirements supply the dependency list.
Platform markers are evaluated for the scanner's environment.

The audit requires access to the package index and vulnerability service.
A scanner error is a failed check. No vulnerability IDs are ignored, and
the check does not use automatic fixes or filter findings by severity.

## Evidence

Each local run creates a private directory under `backups/dependency-audit-*`.
It prints the directory before scanning. The files record:

- Start time in UTC, checkout commit, and whether the working tree was modified.
- Hashes of `pyproject.toml` and `uv.lock`.
- Exported requirements, scanner version, and scanner exit code.
- `audit.json`, when the scanner produces a report.

A modified working tree means the commit alone does not identify all local
files; use the recorded input hashes when comparing results. Failed runs
can leave partial evidence. The script reports success only after the
scanner exits successfully and the report contains nonempty dependency
results with no skips, missing vulnerability fields, or reported findings.

An optional first argument selects a new report directory. Its parent must
exist, and the report directory itself must not exist, so an older report
cannot be mistaken for output from a new scan:

```bash
./scripts/check_dependencies.sh /tmp/appops-dependency-check
```

The default `backups/` evidence directories are excluded from Git.

## CI behavior

CI runs the same script after code checks and unit tests, before the image
build. The job fails if the lockfile cannot be exported, the scanner fails,
or the report validation fails. The publishing job depends on successful
checks, so a failed audit blocks image publishing. There is no
`continue-on-error` exception for this step.

After a successful or failed audit step, CI uploads the available report
directory as `dependency-audit-<run attempt>` with 14-day retention. A
cancelled run is not guaranteed to upload evidence. If the failure occurred
before the report was written, use the failed step's log and any partial
artifact to diagnose it. The artifact contains package audit data, not
environment files or database backups.

The tests in `tests/test_dependency_audit.py` check scanner failure exit
codes, lock-export failure, and rejection of empty, skipped, incomplete,
malformed, or vulnerable reports. They use synthetic scanner responses and
do not install vulnerable packages or contact the advisory service.

## If the check fails

Inspect `audit.json` and the failed step log first. Findings include package
versions and advisory details; distinguish them from network or collection
errors. Fix infrastructure or connectivity errors and rerun the scan rather
than treating incomplete output as a clean result.

For a reported vulnerability, review the upstream advisory and fixed
versions, update the affected dependency constraint or lock entry, and run
the audit and application tests again. Review the resulting lockfile diff
before committing. A dependency update does not replace the running
application until it goes through the normal release and deployment process.

## Verified baseline — 13 November 2026

The initial WSL scan used checkout `598ba82`, Python 3.14, and
`pip-audit 2.10.1`, after the staging and production Ansible rehearsals.

| Check | Recorded result |
| --- | --- |
| Applicable Python packages audited | 31 |
| Skipped packages | 0 |
| Known vulnerabilities reported | 0 |
| Working tree after the scan | Clean |
| Local evidence | `backups/dependency-audit-20261113T052751Z-HgBtxd` |

That baseline directory contains the exported requirements, audit JSON,
scanner version, source commit, and the lockfile hash. It predates the
reusable script, so it does not contain every metadata file listed above.

This is a point-in-time result against known advisories, not a guarantee
that the application is vulnerability-free. The scan does not cover
container OS packages, PostgreSQL, Nginx, separately installed Ansible or
other CI tooling, application source-code flaws, or unknown vulnerabilities.
It audits the current checkout's lockfile, not the contents of the already
running application containers. Other platforms can select different
dependencies from the same lockfile.

References: [pip-audit](https://github.com/pypa/pip-audit) and
[uv lockfile export](https://docs.astral.sh/uv/concepts/projects/export/).
