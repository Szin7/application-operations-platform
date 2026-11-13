"""Exercise event correlation and recovery without stopping real containers."""

import copy
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def drill(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "delivery_check", scripts / "check_alert_delivery.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def event():
    return {
        "id": "new-event",
        "received_at": "2026-11-13T12:02:00+00:00",
        "notification": {
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "fingerprint": "matching-fingerprint",
                    "startsAt": "2026-11-13T12:00:15Z",
                    "endsAt": "0001-01-01T00:00:00Z",
                    "labels": {
                        "alertname": "ReadinessCheckFailed",
                        "environment": "staging",
                        "route": "proxy",
                    },
                }
            ],
        },
    }


def test_new_individual_firing_alert_matches(drill, event):
    labels = event["notification"]["alerts"][0]["labels"]
    result = drill.match_notification(
        [event], set(), labels, "firing", "2026-11-13T12:00:00Z"
    )
    assert result["event"]["id"] == "new-event"


@pytest.mark.parametrize(
    "invalid", ["seen", "old_event", "old_alert", "wrong_route", "group_only"]
)
def test_unrelated_events_cannot_pass(drill, event, invalid):
    labels = dict(event["notification"]["alerts"][0]["labels"])
    seen = set()
    alert = event["notification"]["alerts"][0]
    if invalid == "seen":
        seen.add(event["id"])
    elif invalid == "old_event":
        event["received_at"] = "2026-11-13T11:59:59Z"
    elif invalid == "old_alert":
        alert["startsAt"] = "2026-11-13T11:59:59Z"
    elif invalid == "wrong_route":
        alert["labels"]["route"] = "direct"
    else:
        alert["status"] = "resolved"
    assert (
        drill.match_notification(
            [event], seen, labels, "firing", "2026-11-13T12:00:00Z"
        )
        is None
    )


@pytest.mark.parametrize(
    "change", [None, "fingerprint", "startsAt", "labels", "endsAt"]
)
def test_recovery_must_match_the_same_alert_episode(drill, event, change):
    firing = copy.deepcopy(event["notification"]["alerts"][0])
    alert = event["notification"]["alerts"][0]
    alert.update(status="resolved", endsAt="2026-11-13T12:01:45Z")
    if change == "fingerprint":
        alert[change] = "different"
    elif change == "startsAt":
        alert[change] = "2026-11-13T12:00:30Z"
    elif change == "labels":
        alert[change]["another_label"] = "different"
    elif change == "endsAt":
        alert[change] = firing["startsAt"]
    # A group may still be firing for another alert while this alert has resolved.
    result = drill.match_notification(
        [event], set(), firing["labels"], "resolved", "2026-11-13T12:01:30Z", firing
    )
    assert bool(result) is (change is None)


@pytest.mark.parametrize(
    "failure",
    ["stop_timeout", "notification_timeout", "interrupted", "protected_change"],
)
def test_failure_always_attempts_original_container_recovery(
    drill, monkeypatch, failure
):
    spec = drill.DRILLS[0]
    original = {
        "id": "original-id",
        "image": "original-image",
        "running": True,
        "health": "healthy",
    }
    monkeypatch.setattr(
        drill,
        "running_lab",
        lambda: {spec["container"]: original, "protected": {"id": "protected-id"}},
    )
    protect = Mock(return_value={})
    monkeypatch.setattr(drill, "protect", protect)
    monkeypatch.setattr(drill, "active_alerts", lambda labels: [])
    monkeypatch.setattr(drill, "read_json", lambda url: [])
    monkeypatch.setattr(
        drill,
        "snapshot",
        lambda ids: {spec["container"]: {**original, "running": False}},
    )
    command = Mock()
    monkeypatch.setattr(drill, "output", command)
    if failure == "stop_timeout":
        command.side_effect = TimeoutError("Docker stop timed out")
    else:
        error = (
            KeyboardInterrupt()
            if failure == "interrupted"
            else RuntimeError("check failed")
        )

        def wait(*args, **kwargs):
            if failure == "protected_change":
                protect.side_effect = RuntimeError("protected changed")
                args[2]()
            raise error

        monkeypatch.setattr(drill, "wait_for", wait)
    restore = Mock(return_value=original)
    monkeypatch.setattr(drill, "restore_container", restore)
    with pytest.raises((TimeoutError, RuntimeError, KeyboardInterrupt)):
        drill.run_drill(spec, {"id": 1}, {}, lambda: None)
    restore.assert_called_once_with(spec["container"], original)
    assert command.call_args.args == ("docker", "stop", "--time", "10", "original-id")


def test_existing_alert_prevents_any_stop(drill, monkeypatch):
    spec = drill.DRILLS[0]
    monkeypatch.setattr(
        drill,
        "running_lab",
        lambda: {
            spec["container"]: {
                "id": "original-id",
                "running": True,
                "health": "healthy",
            }
        },
    )
    monkeypatch.setattr(drill, "protect", Mock())
    monkeypatch.setattr(drill, "active_alerts", lambda labels: [{"state": "pending"}])
    command = Mock()
    monkeypatch.setattr(drill, "output", command)
    with pytest.raises(RuntimeError, match="already pending"):
        drill.run_drill(spec, {"id": 1}, {}, lambda: None)
    command.assert_not_called()


def test_production_ticket_change_fails_guard(drill, monkeypatch):
    before = {"production": {"id": "production-id"}}
    monkeypatch.setattr(drill, "snapshot", lambda ids: before)
    monkeypatch.setattr(
        drill,
        "read_json",
        lambda url: (
            {"status": "ready"} if "health" in url else {"id": 1, "title": "changed"}
        ),
    )
    with pytest.raises(RuntimeError, match="production ticket"):
        drill.protect(before, (8003, 8083), {"id": 1, "title": "original"})


def test_complete_drill_records_firing_restoration_and_resolution(
    drill, monkeypatch, event
):
    spec = drill.DRILLS[0]
    original = {
        "id": "original-id",
        "image": "original-image",
        "running": True,
        "health": "healthy",
    }
    event["received_at"] = "2026-11-13T12:01:10Z"
    event["notification"]["alerts"][0]["labels"] = spec["labels"]
    resolved = copy.deepcopy(event)
    resolved.update(id="resolved-event", received_at="2026-11-13T12:01:45Z")
    resolved["notification"]["alerts"][0].update(
        status="resolved", endsAt="2026-11-13T12:01:30Z"
    )
    monkeypatch.setattr(
        drill,
        "running_lab",
        lambda: {spec["container"]: original, "protected": {"id": "protected-id"}},
    )
    monkeypatch.setattr(
        drill, "protect", Mock(return_value={"protected": {"id": "protected-id"}})
    )
    monkeypatch.setattr(
        drill, "active_alerts", Mock(side_effect=[[], [{"state": "firing"}], []])
    )
    monkeypatch.setattr(
        drill, "read_json", Mock(side_effect=[[], [event], [event, resolved]])
    )
    monkeypatch.setattr(
        drill,
        "snapshot",
        lambda ids: {spec["container"]: {**original, "running": False}},
    )
    monkeypatch.setattr(drill, "output", Mock())
    monkeypatch.setattr(drill, "readiness", Mock())
    restore = Mock(return_value=original)
    monkeypatch.setattr(drill, "restore_container", restore)
    monkeypatch.setattr(
        drill,
        "now",
        Mock(
            side_effect=[
                "2026-11-13T12:00:00Z",
                "2026-11-13T12:01:15Z",
                "2026-11-13T12:01:50Z",
            ]
        ),
    )
    record = {}
    drill.run_drill(spec, {"id": 1}, record, lambda: None)
    assert record["status"] == "passed"
    assert record["firing"]["event"]["id"] == "new-event"
    assert record["resolved"]["event"]["id"] == "resolved-event"
    restore.assert_called_once_with(spec["container"], original)
