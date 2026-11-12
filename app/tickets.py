from datetime import datetime
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, HTTPException, Path
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.database import get_connection

router = APIRouter(prefix="/tickets", tags=["tickets"])

Priority = Literal["low", "medium", "high", "critical"]
TicketStatus = Literal["open", "in_progress", "resolved"]
TicketTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: TicketTitle
    description: str = Field(default="", max_length=5000)
    priority: Priority = "medium"


class TicketRead(BaseModel):
    id: int
    title: str
    description: str
    priority: Priority
    status: TicketStatus
    created_at: datetime


@router.post("", response_model=TicketRead, status_code=201)
def create_ticket(ticket: TicketCreate):
    try:
        with (
            get_connection() as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute(
                """
                    INSERT INTO app.tickets (title, description, priority)
                    VALUES (%s, %s, %s)
                    RETURNING id, title, description, priority, status, created_at
                    """,
                (ticket.title, ticket.description, ticket.priority),
            )
            row = cursor.fetchone()
    except psycopg.OperationalError, psycopg.InterfaceError, ValueError:
        raise HTTPException(status_code=503, detail="Database unavailable") from None

    return row


@router.get("/{ticket_id}", response_model=TicketRead)
def get_ticket(
    ticket_id: Annotated[int, Path(ge=1, le=9223372036854775807)],
):
    try:
        with (
            get_connection() as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            cursor.execute(
                """
                    SELECT id, title, description, priority, status, created_at
                    FROM app.tickets
                    WHERE id = %s
                    """,
                (ticket_id,),
            )
            row = cursor.fetchone()
    except psycopg.OperationalError, psycopg.InterfaceError, ValueError:
        raise HTTPException(status_code=503, detail="Database unavailable") from None

    if row is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return row
