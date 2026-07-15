from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import get_settings
from .database import SessionLocal, create_schema
from .errors import AppError, app_error_handler
from .routers import admin, auth, files, targets, terminals


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if get_settings().auto_create_schema:
        await create_schema()
    yield


app = FastAPI(title="WebShell API", version="0.1.0", lifespan=lifespan)
app.add_exception_handler(AppError, app_error_handler)
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    started = time.monotonic()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Server-Timing"] = f"app;dur={(time.monotonic() - started) * 1000:.1f}"
    return response


@app.get("/health/live", tags=["health"])
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def ready() -> dict[str, str]:
    async with SessionLocal() as db:
        await db.execute(text("SELECT 1"))
    key_path = get_settings().credential_key_path
    if not key_path.exists() or not key_path.is_file():
        raise AppError(503, "CREDENTIAL_KEY_MISSING", "凭据主密钥不可用")
    return {"status": "ready"}


app.include_router(auth.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(targets.router, prefix="/api/v1")
app.include_router(terminals.router, prefix="/api/v1")
app.include_router(files.router, prefix="/api/v1")
