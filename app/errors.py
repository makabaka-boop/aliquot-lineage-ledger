from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """Business-rule failure carrying its own HTTP status and stable error code."""

    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


# Error codes used across the API ------------------------------------------------
# 422 VALIDATION_ERROR      unknown fields / non-positive / non-integer amounts / malformed body
# 404 TUBE_NOT_FOUND        referenced parent (or queried) tube does not exist
# 412 REVISION_CONFLICT     expected_revision != parent's current revision
# 409 INSUFFICIENT_BALANCE  requested child total exceeds the current balance
# 409 IDEMPOTENCY_CONFLICT  same request_key, different body
# 409 TUBE_ALREADY_EXISTS   register/split reuses an existing tube id
# 409 SPLIT_DUPLICATE       child ids repeat inside one request


def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    body: dict = {
        "error": {
            "code": exc.code,
            "message": exc.message,
        }
    }
    if exc.details:
        body["error"]["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=body)
