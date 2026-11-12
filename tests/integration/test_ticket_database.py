import os

import pytest
from fastapi.testclient import TestClient

from app.database import get_connection
from app.main import app

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="Enable with RUN_DB_TESTS=1 and the test environment",
)

EXPECTED_IDENTITY = ("appops_test", "appops_test_app")


def verify_test_database(connection):
    identity = connection.execute("SELECT current_database(), current_user").fetchone()
    if identity != EXPECTED_IDENTITY:
        pytest.fail("Refusing to run against a non-test database")


@pytest.fixture
def ticket_api():
    if (
        os.environ.get("APP_DB_NAME"),
        os.environ.get("APP_DB_USER"),
    ) != EXPECTED_IDENTITY:
        pytest.fail("Load .env.test before enabling database tests")

    with get_connection() as connection:
        verify_test_database(connection)
        count = connection.execute("SELECT count(*) FROM app.tickets").fetchone()[0]
        if count != 0:
            pytest.fail("Expected an empty test table; no existing rows were removed")

    created_ids = []

    with TestClient(app) as client:

        def create_ticket(title, priority="medium"):
            response = client.post(
                "/tickets",
                json={"title": title, "priority": priority},
            )
            assert response.status_code == 201, response.text
            ticket = response.json()
            created_ids.append(ticket["id"])
            return ticket

        try:
            yield client, create_ticket
        finally:
            if created_ids:
                with get_connection() as connection:
                    verify_test_database(connection)
                    connection.execute(
                        "DELETE FROM app.tickets WHERE id = ANY(%s)",
                        (created_ids,),
                    )


def test_create_read_and_update_persist(ticket_api):
    client, create_ticket = ticket_api
    created = create_ticket("Investigate customer's login issue")

    assert created["status"] == "open"
    assert created["priority"] == "medium"

    fetched = client.get(f"/tickets/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created

    updated = client.patch(
        f"/tickets/{created['id']}/status",
        json={"status": "resolved"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "resolved"
    assert updated.json()["created_at"] == created["created_at"]

    with get_connection() as connection:
        row = connection.execute(
            "SELECT title, status FROM app.tickets WHERE id = %s",
            (created["id"],),
        ).fetchone()

    assert row == ("Investigate customer's login issue", "resolved")

    fetched_again = client.get(f"/tickets/{created['id']}")
    assert fetched_again.status_code == 200
    assert fetched_again.json() == updated.json()


def test_listing_filters_orders_and_paginates(ticket_api):
    client, create_ticket = ticket_api
    first = create_ticket("First ticket")
    second = create_ticket("Second ticket", priority="high")
    third = create_ticket("Third ticket")

    updated = client.patch(
        f"/tickets/{second['id']}/status",
        json={"status": "resolved"},
    )
    assert updated.status_code == 200

    listed = client.get("/tickets")
    assert listed.status_code == 200
    assert [ticket["id"] for ticket in listed.json()] == [
        third["id"],
        second["id"],
        first["id"],
    ]

    page = client.get("/tickets?limit=1&offset=1")
    assert page.status_code == 200
    assert [ticket["id"] for ticket in page.json()] == [second["id"]]

    resolved = client.get("/tickets?status=resolved")
    assert resolved.status_code == 200
    assert [ticket["id"] for ticket in resolved.json()] == [second["id"]]

    opened = client.get("/tickets?status=open&limit=1&offset=1")
    assert opened.status_code == 200
    assert [ticket["id"] for ticket in opened.json()] == [first["id"]]

    empty_page = client.get("/tickets?offset=100")
    assert empty_page.status_code == 200
    assert empty_page.json() == []
