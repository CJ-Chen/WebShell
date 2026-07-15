from __future__ import annotations

import uuid

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, detail: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    payload = {"code": exc.code, "message": exc.message, "request_id": request_id}
    if exc.detail:
        payload["detail"] = exc.detail
    return JSONResponse(status_code=exc.status_code, content=payload)
