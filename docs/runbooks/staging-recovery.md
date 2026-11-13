# Staging startup failure and recovery

This rehearsal applies an invalid startup command to the staging API, confirms
that the rollout failed for the intended reason, and restores the saved image
with `scripts/rollback.sh`. The image is unchanged. This is a local deployment
configuration failure, not an image promotion through GitHub Actions.

## Before running

Both application stacks, their proxies, and the monitoring services should be
healthy. Keep the terminal open and do not deploy, restart services, or edit
tickets during the drill. The original production ticket record must exist at
`backups/rollback-check.json`. The saved staging image must be available locally
and its migration revision must match the staging database.

```bash
uv run --locked python -m pytest tests/test_staging_recovery.py -q
uv run --locked python scripts/check_staging_recovery.py
```

## What the drill does

1. Checks the saved releases against the running image IDs and compares the
   staging image's migration revision with the database.
2. Records the staging ticket table's row count and digest, protected container
   identities, and production readiness through its direct and proxy routes.
3. Writes a temporary Compose override beneath `backups/`. The override changes
   only the staging API startup command, which prints a known marker and exits
   with code 42. The rollout uses `--no-deps`, `--no-build`, and `--pull never`.
4. Requires a nonzero Compose result, a replacement container running the saved
   image, the expected command and exit code, the matching log marker, and both
   staging routes being unavailable. An unrelated Docker failure is not a pass.
5. Invokes the existing staging rollback script in a cleanup block, including
   when the rollout errors, times out, or receives an ordinary interruption.
6. Waits for both staging routes to recover. Checks the image, migration revision,
   all staging ticket rows, saved environment settings, and protected containers.

The staging proxy may temporarily become unhealthy because its health check
depends on the API. Its identity, image, start time, and running state must stay
unchanged; it must return to healthy after rollback.

Production readiness and its original ticket are sampled while rollout and
rollback commands run. A protection failure makes the drill fail; it does not
stop an already running recovery attempt. Sampling cannot prove that there was
no shorter interruption between checks.

## Evidence and diagnosis

Each run writes `backups/staging-recovery-<UTC timestamp>/` containing:

- `fault.json`: the temporary staging-only Compose override.
- `failed-rollout.log`: output of the deliberately failing Compose command.
- `rollback.log`: output of the recovery command.
- `evidence.json`: result, timestamps, source identity, expected failure,
  protection checks, recovered API, and staging database comparisons.

These records are ignored by Git. Review the result before adding a concise
verified outcome to the evidence page. Keep raw logs local. The expected fault
is a startup command exiting with code 42; this is not evidence of a database
failure or an unhealthy application image.

The override is not used by normal deployment or rollback commands. No database
bootstrap, migration, restore, volume removal, or production deployment is run
by this drill. The rollback script checks migration compatibility before it
recreates the staging API. Nginx refreshes Docker DNS for the replacement API.

## If recovery fails

Read `rollback.log` first. The script prints the recovery image before changing
staging and records it as `saved_release` in `evidence.json`. Retry the existing
rollback command with that recorded image:

```bash
./scripts/rollback.sh staging application-operations-platform:<recorded-12-character-commit>
curl --fail http://127.0.0.1:8002/health/ready
curl --fail http://127.0.0.1:8082/health/ready
```

Replace the placeholder with the exact recorded value. Do not remove volumes or
bypass a migration mismatch. Cleanup handles normal exceptions, SIGINT, and
SIGTERM, but cannot run after power loss, SIGKILL, or Docker becoming unavailable.
A second ordinary interruption is ignored while the bounded cleanup runs.

## Verification status

The automated tests exercise failure attribution, process timeout cleanup,
interruption handling, protected-state failures during recovery, rollback
failure, and changed staging data. The local code check passed with 103 tests
passing and the two opt-in database integration tests skipped.

## Verified exercise — 13 November 2026

The WSL rehearsal passed using saved release
`application-operations-platform:a56088c1b7bb`. The temporary startup command
exited with the intended code 42, and both staging readiness routes became
unavailable. The existing rollback script restored the saved image; direct
and proxied staging readiness recovered.

The staging migration revision and the count and digest of all staging ticket
rows matched their starting values. Protected containers and production
settings were unchanged. Production readiness and the original production
ticket passed the sampled protection checks. All four readiness routes passed
at the end.

Local evidence:
`backups/staging-recovery-20261113T123703731666Z/evidence.json`.
The final result was `passed`. Raw evidence and command logs remain local.
This verified a configuration-failure recovery using the same image; it did
not test a failing image promoted through GitHub Actions.
