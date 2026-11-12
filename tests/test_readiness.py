import psycopg
from fastapi.testclient import TestClient

from app import main


def test_readiness_when_database_is_available(monkeypatch):
    def successful_check():
        return None

    monkeypatch.setattr(main, "check_database", successful_check)

    with TestClient(main.app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_database_failure_affects_readiness_but_not_liveness(monkeypatch):
    def failed_check():
        raise psycopg.OperationalError("Private connection details")

    monkeypatch.setattr(main, "check_database", failed_check)

    with TestClient(main.app) as client:
        ready = client.get("/health/ready")
        live = client.get("/health/live")

    assert ready.status_code == 503
    assert ready.json() == {"detail": "Database unavailable"}
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
