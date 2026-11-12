import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from app import metrics


@pytest.fixture
def monitored_app():
    registry = CollectorRegistry()
    application = FastAPI()
    metrics.add_metrics(application, registry)

    @application.get("/items/{item_id}")
    def item(item_id: int):
        return {"id": item_id}

    @application.get("/unavailable")
    def unavailable():
        raise HTTPException(status_code=503, detail="Unavailable")

    @application.get("/broken")
    def broken():
        raise RuntimeError("Private failure details")

    with TestClient(application, raise_server_exceptions=False) as client:
        yield client, registry


def request_samples(registry):
    return [
        sample
        for family in registry.collect()
        for sample in family.samples
        if sample.name == "app_http_requests_total"
    ]


def test_requests_share_the_route_template(monitored_app):
    client, registry = monitored_app
    assert client.get("/items/1").status_code == 200
    assert client.get("/items/2?source=test").status_code == 200

    samples = request_samples(registry)
    assert len(samples) == 1
    assert samples[0].labels == {
        "method": "GET",
        "route": "/items/{item_id}",
        "status": "200",
    }
    assert samples[0].value == 2
    assert (
        registry.get_sample_value(
            "app_http_request_duration_seconds_count",
            {"method": "GET", "route": "/items/{item_id}"},
        )
        == 2
    )


@pytest.mark.parametrize(
    ("path", "route", "status"),
    [
        ("/missing", "unmatched", 404),
        ("/items/invalid", "/items/{item_id}", 422),
        ("/unavailable", "/unavailable", 503),
        ("/broken", "/broken", 500),
    ],
)
def test_error_responses_are_counted(monitored_app, path, route, status):
    client, registry = monitored_app
    response = client.get(path)

    assert response.status_code == status
    assert (
        registry.get_sample_value(
            "app_http_requests_total",
            {"method": "GET", "route": route, "status": str(status)},
        )
        == 1
    )


def test_reading_metrics_does_not_count_as_traffic(monitored_app):
    client, registry = monitored_app
    client.get("/items/1")

    for _ in range(2):
        response = client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert "app_http_requests_total" in response.text

    samples = request_samples(registry)
    assert len(samples) == 1
    assert samples[0].value == 1


def test_unknown_methods_share_one_label(monitored_app):
    client, registry = monitored_app
    for method in ("BREW", "CUSTOM"):
        assert client.request(method, "/missing").status_code == 404

    samples = request_samples(registry)
    assert len(samples) == 1
    assert samples[0].labels["method"] == "OTHER"
    assert samples[0].labels["route"] == "unmatched"
    assert samples[0].value == 2


def test_duration_is_recorded_in_seconds(monitored_app, monkeypatch):
    client, registry = monitored_app
    clock = iter((10.0, 10.25))
    monkeypatch.setattr(metrics, "perf_counter", lambda: next(clock))

    assert client.get("/items/1").status_code == 200
    assert registry.get_sample_value(
        "app_http_request_duration_seconds_sum",
        {"method": "GET", "route": "/items/{item_id}"},
    ) == pytest.approx(0.25)


def test_application_exposes_metrics():
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/metrics")

    assert response.status_code == 200
    assert 'route="/health/live"' in response.text
    assert "app_http_request_duration_seconds_bucket" in response.text
