"""Check fault attribution, cleanup, and protected-state handling without Docker."""

import copy
import importlib.util
import json
import signal
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def drill(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "staging_check", scripts / "check_staging_recovery.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def failed_container(drill):
    return {
        "Id": "replacement",
        "Image": "saved-image",
        "Config": {"Cmd": drill.FAULT_COMMAND},
        "State": {"Running": False, "ExitCode": 42},
    }


def test_intended_failure_is_accepted(drill, failed_container):
    drill.validate_failure(
        1, {"id": "old", "image": "saved-image"}, failed_container, drill.MARKER
    )


@pytest.mark.parametrize(
    "change",
    [
        "success",
        "old_container",
        "wrong_image",
        "wrong_command",
        "running",
        "wrong_exit",
        "missing_log",
    ],
)
def test_unrelated_failures_are_rejected(drill, failed_container, change):
    code, logs = 1, drill.MARKER
    if change == "success":
        code = 0
    elif change == "old_container":
        failed_container["Id"] = "old"
    elif change == "wrong_image":
        failed_container["Image"] = "different"
    elif change == "wrong_command":
        failed_container["Config"]["Cmd"] = ["other"]
    elif change == "running":
        failed_container["State"]["Running"] = True
    elif change == "wrong_exit":
        failed_container["State"]["ExitCode"] = 1
    else:
        logs = "unrelated error"
    with pytest.raises(RuntimeError):
        drill.validate_failure(
            code, {"id": "old", "image": "saved-image"}, failed_container, logs
        )


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("fault"),
        KeyboardInterrupt(),
        subprocess.TimeoutExpired("compose", 90),
    ],
)
def test_failure_always_recovers_and_restores_signal_handlers(drill, error):
    previous = signal.getsignal(signal.SIGINT)
    recovered = Mock()
    with pytest.raises(type(error)):
        drill.with_recovery(Mock(side_effect=error), recovered)
    recovered.assert_called_once_with()
    assert signal.getsignal(signal.SIGINT) == previous


def test_success_also_recovers(drill):
    recovered = Mock()
    assert drill.with_recovery(lambda: "observed", recovered) == "observed"
    recovered.assert_called_once_with()


@pytest.mark.parametrize("reason", ["guard", "timeout", "interrupt"])
def test_child_stops_before_recovery_on_abort(drill, monkeypatch, tmp_path, reason):
    process = Mock(pid=123, returncode=None)
    process.poll.return_value = None
    monkeypatch.setattr(drill.subprocess, "Popen", Mock(return_value=process))
    clock = iter([0, 2])
    monkeypatch.setattr(drill.time, "monotonic", lambda: next(clock))
    stop = Mock()
    monkeypatch.setattr(drill, "stop_process", stop)
    error = KeyboardInterrupt if reason == "interrupt" else RuntimeError
    guard = Mock(side_effect=error("guard")) if reason != "timeout" else Mock()
    with pytest.raises(error):
        drill.execute(["fake"], tmp_path / "log", guard, {}, timeout=1)
    stop.assert_called_once_with(process)


def test_stuck_child_escalates_to_kill(drill, monkeypatch):
    process = Mock(pid=123)
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("fake", 10), 0]
    kill = Mock()
    monkeypatch.setattr(drill.os, "killpg", kill)
    drill.stop_process(process)
    assert [c.args for c in kill.call_args_list] == [
        (123, signal.SIGTERM),
        (123, signal.SIGKILL),
    ]


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "inject_timeout",
        "protected_change",
        "recovery_guard",
        "rollback_failed",
        "data_changed",
    ],
)
def test_full_rehearsal_and_failure_evidence(drill, monkeypatch, tmp_path, fault):
    monkeypatch.setattr(drill, "ROOT", tmp_path)
    for name in ("staging", "production"):
        (tmp_path / f".env.{name}").write_text(
            "APP_IMAGE=application-operations-platform:a56088c1b7bb\n"
        )
    monkeypatch.delenv("APP_IMAGE", raising=False)
    backup = tmp_path / "backups"
    backup.mkdir()
    (backup / "rollback-check.json").write_text(json.dumps({"ticket": {"id": 1}}))
    names = [
        drill.TARGET,
        "application-operations-staging-db-1",
        "application-operations-production-api-1",
        "application-operations-production-db-1",
        "application-operations-proxy-staging-1",
        "application-operations-proxy-production-1",
    ]
    before = {
        n: {"id": n, "image": "saved-image", "health": "healthy", "running": True}
        for n in names
    }
    phase = {"value": "before"}
    monkeypatch.setattr(drill, "running_lab", lambda: copy.deepcopy(before))
    monkeypatch.setattr(
        drill, "snapshot", lambda ids: {name: before[name] for name in ids}
    )
    monkeypatch.setattr(drill, "readiness", Mock())
    monkeypatch.setattr(drill, "read_json", lambda url: {"status": "ready"})
    monkeypatch.setattr(
        drill, "failed_route", lambda port: {"port": port, "result": "unreachable"}
    )
    states = [
        {"revision": "0001", "count": 1, "digest": "same"},
        {
            "revision": "0001",
            "count": 1,
            "digest": "changed" if fault == "data_changed" else "same",
        },
    ]
    monkeypatch.setattr(drill, "database_state", Mock(side_effect=states))

    def protect(*args):
        if (fault == "protected_change" and phase["value"] == "inject") or (
            fault == "recovery_guard" and phase["value"] == "recover"
        ):
            raise RuntimeError("protected state changed")

    monkeypatch.setattr(drill, "protect", protect)

    def output(*command):
        if command[:3] == ("docker", "image", "inspect"):
            return "saved-image"
        if command[:2] == ("docker", "run"):
            return "0001"
        if command[:2] == ("docker", "inspect"):
            return json.dumps(
                [
                    {
                        "Id": "replacement",
                        "Image": "saved-image",
                        "Config": {"Cmd": drill.FAULT_COMMAND},
                        "State": {"Running": False, "ExitCode": 42},
                    }
                ]
            )
        if command[:2] == ("docker", "logs"):
            return drill.MARKER
        return "source-commit"

    monkeypatch.setattr(drill, "output", output)
    commands = []

    def execute(command, log, guard, env, timeout=180):
        commands.append(command)
        if command[0] == "bash":
            phase["value"] = "recover"
            guard()
            return 1 if fault == "rollback_failed" else 0
        phase["value"] = "inject"
        guard()
        if fault == "inject_timeout":
            raise subprocess.TimeoutExpired(command, timeout)
        return 1

    monkeypatch.setattr(drill, "execute", execute)
    if fault:
        with pytest.raises((RuntimeError, subprocess.TimeoutExpired)):
            drill.run(backup)
    else:
        drill.run(backup)
    assert len(commands) == 2
    assert commands[0][-1] == "api"
    assert "--no-deps" in commands[0]
    assert commands[1] == [
        "bash",
        "scripts/rollback.sh",
        "staging",
        "application-operations-platform:a56088c1b7bb",
    ]
    evidence = json.loads(
        next(backup.glob("staging-recovery-*/evidence.json")).read_text()
    )
    assert evidence["status"] == ("failed" if fault else "passed")
    if fault == "recovery_guard":
        assert "recovery" in evidence  # Guard failure did not interrupt recovery.
    assert (
        tmp_path / ".env.production"
    ).read_text() == "APP_IMAGE=application-operations-platform:a56088c1b7bb\n"


@pytest.mark.parametrize(
    "field,value,allowed",
    [
        ("health", "unhealthy", True),
        ("id", "new", False),
        ("running", False, False),
        ("started_at", "new", False),
    ],
)
def test_proxy_can_lose_health_but_cannot_restart(
    drill, monkeypatch, field, value, allowed
):
    original = {
        "id": "proxy",
        "image": "nginx",
        "running": True,
        "health": "healthy",
        "started_at": "before",
    }
    current = {**original, field: value}
    monkeypatch.setattr(drill, "snapshot", lambda ids: {drill.PROXY: current})
    if allowed:
        assert drill.protect_proxy(original) == current
    else:
        with pytest.raises(RuntimeError):
            drill.protect_proxy(original)
