import json
from collections import deque
from datetime import datetime
from http.client import HTTPConnection
from http.server import HTTPServer
from threading import Thread

import pytest

from scripts import alert_receiver


@pytest.fixture
def receiver(monkeypatch):
    monkeypatch.setattr(alert_receiver, "events", deque(maxlen=100))

    with HTTPServer(("127.0.0.1", 0), alert_receiver.AlertReceiver) as server:
        worker = Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        worker.start()

        def request(method, path, body=None, headers=None):
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                connection.request(method, path, body=body, headers=headers or {})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        try:
            yield request
        finally:
            server.shutdown()
            worker.join(timeout=5)
            assert not worker.is_alive(), "Receiver test server did not stop"


def notification(status):
    return {
        "version": "4",
        "receiver": "local-webhook",
        "status": status,
        "alerts": [
            {
                "status": status,
                "labels": {
                    "alertname": "ApiScrapeFailed",
                    "environment": "staging",
                },
            }
        ],
    }


def test_receiver_starts_with_empty_history(receiver):
    assert receiver("GET", "/health") == (200, {"status": "ok"})
    assert receiver("GET", "/events") == (200, [])


def test_firing_and_recovery_messages_are_recorded(receiver):
    payloads = [notification(status) for status in ("firing", "resolved")]
    received_ids = []

    for payload in payloads:
        status, result = receiver("POST", "/alerts", json.dumps(payload).encode())
        assert status == 200
        assert result["status"] == "received"
        received_ids.append(result["id"])

    status, events = receiver("GET", "/events")
    assert status == 200
    assert [event["notification"] for event in events] == payloads
    assert [event["id"] for event in events] == received_ids
    assert len(set(received_ids)) == 2
    assert all(
        datetime.fromisoformat(event["received_at"]).tzinfo is not None
        for event in events
    )


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"{", id="invalid-json"),
        pytest.param(b"[]", id="wrong-json-type"),
        pytest.param(b'{"status":"firing","alerts":[]}', id="empty-alerts"),
    ],
)
def test_invalid_notifications_are_not_recorded(receiver, body):
    status, _ = receiver("POST", "/alerts", body)

    assert status == 400
    assert receiver("GET", "/events") == (200, [])


@pytest.mark.parametrize(
    ("length", "expected_status"),
    [
        pytest.param("invalid", 400, id="invalid-length"),
        pytest.param("65537", 413, id="oversized-body"),
    ],
)
def test_invalid_body_lengths_are_rejected(receiver, length, expected_status):
    status, _ = receiver("POST", "/alerts", b"", {"Content-Length": length})

    assert status == expected_status
    assert receiver("GET", "/events") == (200, [])


def test_history_keeps_the_latest_100_notifications(receiver):
    body = json.dumps(notification("firing")).encode()
    received_ids = []

    for _ in range(101):
        status, result = receiver("POST", "/alerts", body)
        assert status == 200
        received_ids.append(result["id"])

    status, events = receiver("GET", "/events")
    assert status == 200
    assert [event["id"] for event in events] == received_ids[-100:]
