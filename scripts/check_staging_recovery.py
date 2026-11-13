"""Rehearse a failed staging startup and recover with the existing rollback script."""

import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from check_alert_delivery import protect, read_json
from dotenv import dotenv_values
from start_container_monitoring import running_lab
from start_node_exporter import output, readiness, snapshot

ROOT = Path(__file__).resolve().parents[1]
TARGET = "application-operations-staging-api-1"
PROXY = "application-operations-proxy-staging-1"
MARKER = "Controlled staging drill: startup command exits with code 42."
FAULT_COMMAND = ["python", "-c", f"print({MARKER!r}, flush=True); raise SystemExit(42)"]
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    ".env.staging",
    "--project-name",
    "application-operations-staging",
    "-f",
    "compose.yaml",
    "-f",
    "compose.tools.yaml",
]


def now():
    return datetime.now(UTC).isoformat()


def database_state():
    # Read the entire staging ticket table, but retain only a digest and row count.
    sql = (
        "SELECT json_build_object('revision', "
        "(SELECT version_num FROM public.alembic_version), 'count', count(*), "
        "'digest', md5(COALESCE(jsonb_agg(to_jsonb(t) ORDER BY id)::text, '[]'))) "
        "FROM app.tickets t"
    )
    result = output(
        *COMPOSE,
        "exec",
        "-T",
        "db",
        "sh",
        "-c",
        "exec psql -X --no-password --tuples-only --no-align "
        '--set=ON_ERROR_STOP=1 --username="$POSTGRES_USER" '
        '--dbname="$POSTGRES_DB" --command="$1"',
        "sh",
        sql,
    )
    return json.loads(result)


def stop_process(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)


def execute(command, log, guard, env, timeout=180):
    """Bound the child and stop its process group before attempting recovery."""
    with log.open("w") as stream:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                guard()
                if time.monotonic() >= deadline:
                    raise RuntimeError("Command exceeded its deadline; see local log.")
                time.sleep(2)
            guard()
            return process.returncode
        finally:
            stop_process(process)


def failed_route(port):
    try:
        with urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=5) as response:
            raise RuntimeError(
                f"Staging route {port} still responds: {response.status}"
            )
    except HTTPError as error:
        if error.code < 500:
            raise RuntimeError(
                f"Unexpected staging HTTP status: {error.code}"
            ) from error
        return {"port": port, "http_status": error.code}
    except URLError, TimeoutError, ConnectionError:
        return {"port": port, "result": "unreachable"}


def protect_proxy(original):
    current = snapshot([original["id"]])[PROXY]
    # Its readiness check depends on the intentionally unavailable staging API.
    stable_before = {key: value for key, value in original.items() if key != "health"}
    stable_after = {key: value for key, value in current.items() if key != "health"}
    if stable_before != stable_after:
        raise RuntimeError("Staging proxy identity or runtime changed.")
    return current


def validate_failure(returncode, before, current, logs):
    if returncode == 0:
        raise RuntimeError("Faulty staging rollout unexpectedly succeeded.")
    if current["Id"] == before["id"] or current["Image"] != before["image"]:
        raise RuntimeError("Fault was not applied to a replacement of the saved API.")
    if current["Config"]["Cmd"] != FAULT_COMMAND:
        raise RuntimeError("Replacement API does not have the intended fault.")
    if current["State"]["Running"] or current["State"]["ExitCode"] != 42:
        raise RuntimeError("Staging API did not exit with the intended code 42.")
    if MARKER not in logs:
        raise RuntimeError("Expected startup failure marker is missing.")


def with_recovery(inject, recover):
    # Enter this scope before Compose can replace the original API.
    try:
        return inject()
    finally:
        # A second Ctrl+C must not interrupt the bounded rollback attempt.
        previous = {
            s: signal.signal(s, signal.SIG_IGN) for s in (signal.SIGINT, signal.SIGTERM)
        }
        try:
            recover()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"Received signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    os.chdir(ROOT)
    backup = ROOT / "backups"
    backup.mkdir(exist_ok=True)
    with (backup / ".staging-recovery.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(backup)


def run(backup):
    configs = {
        name: dotenv_values(ROOT / f".env.{name}") for name in ("staging", "production")
    }
    # Refuse shell overrides instead of silently testing a different configuration.
    for config in configs.values():
        conflicts = [key for key in config if key in os.environ]
        if conflicts:
            raise RuntimeError(
                "Unset exported environment settings first: " + ", ".join(conflicts)
            )
    env = os.environ.copy()
    before = running_lab()
    required = {
        TARGET,
        "application-operations-staging-db-1",
        "application-operations-production-api-1",
        "application-operations-production-db-1",
        "application-operations-proxy-staging-1",
        "application-operations-proxy-production-1",
    }
    if not required.issubset(before):
        raise RuntimeError("Both application stacks and proxies must be running.")
    for name in required:
        if not before[name]["running"] or before[name]["health"] != "healthy":
            raise RuntimeError(f"Required container is not healthy: {name}")
    readiness()
    release = configs["staging"].get("APP_IMAGE", "")
    for environment, config in configs.items():
        saved = config.get("APP_IMAGE", "")
        if not re.fullmatch(r"application-operations-platform:[0-9a-f]{12}", saved):
            raise RuntimeError(f"Unexpected saved release: {environment}")
        image = output(
            "docker", "image", "inspect", "--format", "{{.Id}}", saved
        ).strip()
        if image != before[f"application-operations-{environment}-api-1"]["image"]:
            raise RuntimeError(f"Saved release differs from running {environment}")
    good_id = before[TARGET]["image"]
    target_revision = output(
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        "none",
        "--read-only",
        good_id,
        "python",
        "-c",
        "from alembic.config import Config; from alembic.script import ScriptDirectory; "
        'print(ScriptDirectory.from_config(Config("alembic.ini")).get_current_head())',
    ).strip()
    db_before = database_state()
    if target_revision != db_before["revision"]:
        raise RuntimeError("Saved image and staging database migrations do not match.")
    production_env = (ROOT / ".env.production").read_bytes()
    ticket = json.loads((backup / "rollback-check.json").read_text())["ticket"]
    if type(ticket.get("id")) is not int or ticket["id"] <= 0:
        raise RuntimeError("Invalid original production ticket record.")
    protected = {key: value for key, value in before.items() if key != TARGET}
    checks = 0

    def guard():
        nonlocal checks
        protect(
            {key: value for key, value in protected.items() if key != PROXY},
            (8003, 8083),
            ticket,
        )
        protect_proxy(protected[PROXY])
        if (ROOT / ".env.production").read_bytes() != production_env:
            raise RuntimeError("Production environment file changed.")
        checks += 1

    guard()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    folder = backup / f"staging-recovery-{stamp}"
    folder.mkdir(mode=0o700)
    path = folder / "evidence.json"
    override = folder / "fault.json"
    override.write_text(
        json.dumps(
            {
                "services": {
                    "api": {
                        "image": good_id,
                        "command": FAULT_COMMAND,
                        "restart": "no",
                    }
                }
            }
        )
        + "\n"
    )
    evidence = {
        "status": "running",
        "started_at_utc": now(),
        "source_commit": output("git", "rev-parse", "HEAD").strip(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "kind": "staging startup configuration fault; same saved image",
        "saved_release": release,
        "original_api": before[TARGET],
        "protected_before": protected,
        "staging_database_before": db_before,
    }

    def save():
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(evidence, indent=2) + "\n")
        temporary.replace(path)

    save()
    print(f"Evidence directory: {folder.relative_to(ROOT)}", flush=True)
    print(f"Recovery image: {release}", flush=True)
    print("Deploying the controlled startup fault to staging API only...", flush=True)

    def inject():
        guard()
        command = COMPOSE + [
            "-f",
            str(override),
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--pull",
            "never",
            "--wait",
            "--wait-timeout",
            "45",
            "api",
        ]
        code = execute(command, folder / "failed-rollout.log", guard, env, timeout=90)
        current = json.loads(output("docker", "inspect", TARGET))[0]
        logs = output("docker", "logs", "--tail", "20", current["Id"])
        validate_failure(code, before[TARGET], current, logs)
        evidence["failure"] = {
            "compose_exit_code": code,
            "container_id": current["Id"],
            "container_exit_code": 42,
            "startup_marker": MARKER,
            "routes": [failed_route(port) for port in (8002, 8082)],
        }
        if dotenv_values(ROOT / ".env.staging") != configs["staging"]:
            raise RuntimeError("Failed rollout changed the saved staging settings.")
        guard()
        save()
        print(
            "Expected startup failure confirmed: exit 42; both staging routes unavailable.",
            flush=True,
        )

    def recover():
        print("Restoring staging with scripts/rollback.sh...", flush=True)
        guard_errors = []

        def recovery_guard():
            # Continue recovery even if a protection check fails; report it afterwards.
            try:
                guard()
            except (
                RuntimeError,
                OSError,
                ValueError,
                subprocess.SubprocessError,
            ) as error:
                guard_errors.append(str(error))

        code = execute(
            ["bash", "scripts/rollback.sh", "staging", release],
            folder / "rollback.log",
            recovery_guard,
            env,
        )
        if code != 0:
            raise RuntimeError(
                f"Rollback failed; inspect {folder.relative_to(ROOT)}/rollback.log"
            )
        deadline = time.monotonic() + 45
        while True:
            recovery_guard()
            try:
                for port in (8002, 8082):
                    if read_json(f"http://127.0.0.1:{port}/health/ready") != {
                        "status": "ready"
                    }:
                        raise RuntimeError("Staging readiness response differs.")
                break
            except URLError, TimeoutError, ConnectionError, RuntimeError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Staging routes did not recover before the deadline."
                    ) from None
                time.sleep(2)
        evidence["recovery"] = {
            "completed_at_utc": now(),
            "api": snapshot([TARGET])[TARGET],
        }
        save()
        if guard_errors:
            raise RuntimeError(
                "Protection check failed during recovery: " + guard_errors[0]
            )
        print("Staging direct and proxy readiness recovered.", flush=True)

    try:
        with_recovery(inject, recover)
        after = running_lab()
        if set(after) != set(before):
            raise RuntimeError("Running lab inventory changed.")
        if after[TARGET]["image"] != good_id or after[TARGET]["health"] != "healthy":
            raise RuntimeError("Recovered API image or health does not match.")
        db_after = database_state()
        if db_after != db_before:
            raise RuntimeError("Staging migration or ticket data changed.")
        if dotenv_values(ROOT / ".env.staging") != configs["staging"]:
            raise RuntimeError("Recovered staging settings differ.")
        guard()
        readiness()
        evidence.update(
            status="passed",
            staging_database_after=db_after,
            protected_after={key: after[key] for key in protected},
            original_production_ticket="matched at every sampled guard check",
        )
        print("Staging migration and all ticket rows: unchanged.", flush=True)
        print("Protected containers and production settings: unchanged.", flush=True)
        print("Staging failure and recovery check passed.", flush=True)
    except BaseException as error:
        evidence.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        evidence.update(finished_at_utc=now(), production_guard_checks=checks)
        save()
        print(
            f"Evidence saved ({evidence['status']}): {path.relative_to(ROOT)}",
            flush=True,
        )


if __name__ == "__main__":
    main()
