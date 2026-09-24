from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .db import connect, init_db
from .errors import DomainError, domain_error_handler
from .routers import inventory


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create the schema file if the repository/volume is empty (fresh start).
    conn = connect()
    try:
        init_db(conn)
    finally:
        conn.close()
    yield


app = FastAPI(
    title="Sample Tube Inventory",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_exception_handler(DomainError, domain_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "request body failed validation",
                "details": jsonable_encoder(exc.errors()),
            }
        },
    )


app.include_router(inventory.router)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Keep the uniform error envelope even for unexpected failures.
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "unexpected error"}},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
