from time import perf_counter

from fastapi import FastAPI, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

HTTP_METHODS = {
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
    "TRACE",
    "CONNECT",
}


class RequestMetricsMiddleware:
    def __init__(self, app, request_count, request_duration):
        self.app = app
        self.request_count = request_count
        self.request_duration = request_duration

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = perf_counter()
        status = 500

        async def send_response(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            if route != "/metrics":
                method = scope["method"]
                if method not in HTTP_METHODS:
                    method = "OTHER"
                self.request_count.labels(method, route, str(status)).inc()
                self.request_duration.labels(method, route).observe(
                    perf_counter() - started
                )


def add_metrics(app: FastAPI, registry: CollectorRegistry = REGISTRY) -> None:
    request_count = Counter(
        "app_http_requests_total",
        "HTTP requests by method, route, and status.",
        ["method", "route", "status"],
        registry=registry,
    )
    request_duration = Histogram(
        "app_http_request_duration_seconds",
        "Time spent handling HTTP requests in seconds.",
        ["method", "route"],
        registry=registry,
    )
    app.add_middleware(
        RequestMetricsMiddleware,
        request_count=request_count,
        request_duration=request_duration,
    )

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(
            content=generate_latest(registry),
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )
