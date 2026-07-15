from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from .config import get_settings
from .database import get_db
from .errors import AppError
from .models import User, WebSession, utcnow
from .security import token_hash


@dataclass
class AuthContext:
    user: User
    session: WebSession


def _same_request_origin(request: Request, origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    forwarded_host = request.headers.get("x-forwarded-host")
    host = forwarded_host or request.headers.get("host", "")
    return bool(parsed.scheme and parsed.netloc and parsed.netloc.lower() == host.lower())


def validate_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    settings = get_settings()
    if origin.rstrip("/") in {item.rstrip("/") for item in settings.trusted_origins}:
        return
    if _same_request_origin(request, origin):
        return
    raise AppError(403, "INVALID_ORIGIN", "请求来源未获授权")


async def authenticate_token(db: AsyncSession, raw_token: Optional[str]) -> AuthContext:
    if not raw_token:
        raise AppError(401, "AUTH_REQUIRED", "请先登录")
    result = await db.execute(
        select(WebSession)
        .options(joinedload(WebSession.user))
        .where(WebSession.token_hash == token_hash(raw_token))
    )
    session = result.scalar_one_or_none()
    now = utcnow()
    if not session or session.idle_expires_at <= now or session.absolute_expires_at <= now:
        if session:
            await db.delete(session)
            await db.commit()
        raise AppError(401, "SESSION_EXPIRED", "登录会话已过期")
    if session.user.status != "active":
        raise AppError(403, "ACCOUNT_DISABLED", "账号当前不可用")
    settings = get_settings()
    if (now - session.last_seen_at).total_seconds() >= 60:
        session.last_seen_at = now
        session.idle_expires_at = min(
            now + timedelta(seconds=settings.session_idle_seconds), session.absolute_expires_at
        )
        await db.commit()
    return AuthContext(user=session.user, session=session)


async def get_auth_context(
    request: Request, db: AsyncSession = Depends(get_db)
) -> AuthContext:
    raw_token = request.cookies.get(get_settings().session_cookie)
    context = await authenticate_token(db, raw_token)
    request.state.auth = context
    return context


async def get_current_user(context: AuthContext = Depends(get_auth_context)) -> User:
    return context.user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise AppError(403, "ADMIN_REQUIRED", "需要管理员权限")
    return user


async def require_csrf(
    request: Request, context: AuthContext = Depends(get_auth_context)
) -> AuthContext:
    validate_origin(request)
    supplied = request.headers.get("x-csrf-token")
    if not supplied or supplied != context.session.csrf_token:
        raise AppError(403, "CSRF_FAILED", "CSRF 校验失败")
    return context
