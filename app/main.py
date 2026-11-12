import psycopg
from fastapi import FastAPI, HTTPException

from app.database import check_database
from app.metrics import add_metrics
from app.tickets import router as tickets_router

APP_VERSION = "0.1.2"

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


@app.get("/health/ready")
def readiness() -> dict[str, str]:
    try:
        check_database()
    except psycopg.Error, ValueError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from None
    return {"status": "ready"}


@app.get("/version")
def version() -> dict[str, str]:
    return {"version": APP_VERSION}


app.include_router(tickets_router)
add_metrics(app)
