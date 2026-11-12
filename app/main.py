from fastapi import FastAPI

APP_VERSION = "0.1.0"

app = FastAPI(
    title="Application Operations Platform",
    version=APP_VERSION,
)


@app.get("/")
def home() -> dict[str, str]:
    return {"service": "application-operations-platform"}


@app.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
def version() -> dict[str, str]:
    return {"version": APP_VERSION}
