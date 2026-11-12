import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_home_identifies_service():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"service": "application-operations-platform"}


def test_liveness_returns_ok():
    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_matches_project_metadata():
    project_file = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with project_file.open("rb") as file:
        project = tomllib.load(file)

    with TestClient(app) as client:
        response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {"version": project["project"]["version"]}
