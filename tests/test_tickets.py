from unittest.mock import MagicMock

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import tickets
from app.main import app


@pytest.fixture(autouse=True)
def _block_real_database(monkeypatch):
    def unexpected_connection():
        pytest.fail("This test must not connect to the real database")

    monkeypatch.setattr(tickets, "get_connection", unexpected_connection)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="missing-title"),
        pytest.param({"title": ""}, id="empty-title"),
        pytest.param({"title": "   "}, id="blank-title"),
        pytest.param({"title": "x" * 201}, id="long-title"),
        pytest.param(
            {"title": "Valid title", "description": "x" * 5001},
            id="long-description",
        ),
        pytest.param(
            {"title": "Valid title", "priority": "urgent"},
            id="invalid-priority",
        ),
        pytest.param(
            {"title": "Valid title", "id": 99},
            id="unexpected-field",
        ),
    ],
)
def test_invalid_ticket_is_rejected_before_database_access(client, payload):
    response = client.post("/tickets", json=payload)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


@pytest.mark.parametrize(
    "ticket_id",
    ["0", "-1", "abc", "9223372036854775808"],
)
def test_invalid_ticket_id_is_rejected(client, ticket_id):
    response = client.get(f"/tickets/{ticket_id}")

    assert response.status_code == 422


def test_missing_ticket_returns_404(client, monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None

    monkeypatch.setattr(tickets, "get_connection", lambda: connection)

    response = client.get("/tickets/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Ticket not found"}


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_database_failure_returns_503_without_internal_details(
    client, monkeypatch, method
):
    def failed_connection():
        raise psycopg.OperationalError("Private connection details")

    monkeypatch.setattr(tickets, "get_connection", failed_connection)

    if method == "POST":
        response = client.post("/tickets", json={"title": "Valid title"})
    else:
        response = client.get("/tickets/1")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "limit=abc",
        "offset=-1",
        "offset=1000001",
        "status=invalid",
    ],
)
def test_invalid_list_query_is_rejected(client, query):
    response = client.get(f"/tickets?{query}")

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="missing-status"),
        pytest.param({"status": "invalid"}, id="invalid-status"),
        pytest.param({"status": None}, id="null-status"),
        pytest.param(
            {"status": "resolved", "title": "Unexpected change"},
            id="unexpected-field",
        ),
    ],
)
def test_invalid_status_update_is_rejected(client, payload):
    response = client.patch("/tickets/1/status", json=payload)

    assert response.status_code == 422


@pytest.fixture
def database_cursor(monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value

    monkeypatch.setattr(tickets, "get_connection", lambda: connection)
    return cursor


def test_empty_ticket_list_returns_empty_array(client, database_cursor):
    database_cursor.fetchall.return_value = []

    response = client.get("/tickets")

    assert response.status_code == 200
    assert response.json() == []


def test_status_update_for_missing_ticket_returns_404(client, database_cursor):
    database_cursor.fetchone.return_value = None

    response = client.patch(
        "/tickets/999/status",
        json={"status": "resolved"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Ticket not found"}


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/tickets", None),
        ("PATCH", "/tickets/1/status", {"status": "resolved"}),
    ],
)
def test_list_and_update_database_failures(client, monkeypatch, method, path, payload):
    def failed_connection():
        raise psycopg.OperationalError("Private connection details")

    monkeypatch.setattr(tickets, "get_connection", failed_connection)

    response = client.request(method, path, json=payload)

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
