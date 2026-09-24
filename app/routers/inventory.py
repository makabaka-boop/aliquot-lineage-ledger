from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..db import get_db
from ..schemas import RegisterTubeIn, SplitIn
from ..service import get_split, get_tube, list_tubes, register_tube, split_tube

router = APIRouter()


def _validation_response(errors: list[Any]) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "request body failed validation",
                "details": jsonable_encoder(errors),
            }
        },
    )


@router.post("/tubes", status_code=201)
def create_tube(payload: RegisterTubeIn, conn: sqlite3.Connection = Depends(get_db)):
    return register_tube(conn, payload)


@router.get("/tubes")
def read_tubes(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
):
    return list_tubes(conn, limit, offset)


@router.get("/tubes/{tube_id}")
def read_tube(tube_id: str, conn: sqlite3.Connection = Depends(get_db)):
    return get_tube(conn, tube_id)


@router.post("/splits", status_code=201)
async def create_split(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    # Parse once ourselves: the original parsed object must be available for
    # idempotency comparison, and every malformed request must answer 422.
    raw = await request.body()
    try:
        body: Any = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return _validation_response([{"msg": "invalid JSON body"}])
    if not isinstance(body, dict):
        return _validation_response([{"msg": "request body must be a JSON object"}])
    try:
        data = SplitIn.model_validate(body)
    except ValidationError as exc:
        return _validation_response(exc.errors())
    return split_tube(conn, data, body)


@router.get("/splits/{split_id}")
def read_split(split_id: int, conn: sqlite3.Connection = Depends(get_db)):
    return get_split(conn, split_id)
