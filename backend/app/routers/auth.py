from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..dependencies import AuthContext, get_auth_context, require_csrf, validate_origin
from ..errors import AppError
from ..models import User, WebSession, utcnow
from ..schemas import ChangePasswordRequest, LoginRequest, LoginResponse, Message, UserPublic
from ..security import generate_session, hash_password, token_hash, verify_password
from ..services.audit import record_audit
from ..services.encryption import secret_cache
from ..services.rate_limit import rate_limiter


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    validate_origin(request)
    client_ip = request.client.host if request.client else "unknown"
    rate_limiter.check(f"login-ip:{client_ip}", 20, 300)
    rate_limiter.check(f"login-user:{payload.username.lower()}", 10, 300)
    result = await db.execute(
        select(User).where(func.lower(User.username) == payload.username.lower())
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(user.password_hash, payload.password):
        await record_audit(
            db,
            "auth.login",
            "user",
            str(user.id) if user else None,
            outcome="failure",
            detail={"reason": "invalid_credentials"},
            request=request,
        )
        await db.commit()
        raise AppError(401, "INVALID_CREDENTIALS", "用户名或密码错误")
    if user.status != "active":
        raise AppError(403, "ACCOUNT_DISABLED", "账号当前不可用")

    raw_token, csrf_token, idle_expiry, absolute_expiry = generate_session()
    web_session = WebSession(
        user_id=user.id,
        token_hash=token_hash(raw_token),
        csrf_token=csrf_token,
        idle_expires_at=idle_expiry,
        absolute_expires_at=absolute_expiry,
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", "")[:512],
    )
    user.last_login_at = utcnow()
    db.add(web_session)
    await record_audit(db, "auth.login", "user", str(user.id), actor_id=user.id, request=request)
    await db.commit()

    settings = get_settings()
    response.set_cookie(
        settings.session_cookie,
        raw_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.session_absolute_seconds,
        path="/",
    )
    return LoginResponse(user=UserPublic.model_validate(user), csrf_token=csrf_token)


@router.post("/logout", response_model=Message)
async def logout(
    request: Request,
    response: Response,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> Message:
    await record_audit(
        db, "auth.logout", "user", str(context.user.id), actor_id=context.user.id, request=request
    )
    await db.delete(context.session)
    await db.commit()
    secret_cache.remove_user(context.user.id)
    response.delete_cookie(get_settings().session_cookie, path="/")
    return Message(message="已退出登录")


@router.get("/me", response_model=LoginResponse)
async def me(context: AuthContext = Depends(get_auth_context)) -> LoginResponse:
    return LoginResponse(user=UserPublic.model_validate(context.user), csrf_token=context.session.csrf_token)


@router.post("/change-password", response_model=Message)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> Message:
    if not verify_password(context.user.password_hash, payload.current_password):
        raise AppError(400, "CURRENT_PASSWORD_INVALID", "当前密码错误")
    context.user.password_hash = hash_password(payload.new_password)
    context.user.must_change_password = False
    await db.execute(
        delete(WebSession).where(
            WebSession.user_id == context.user.id, WebSession.id != context.session.id
        )
    )
    await record_audit(
        db,
        "auth.password_changed",
        "user",
        str(context.user.id),
        actor_id=context.user.id,
        request=request,
    )
    await db.commit()
    return Message(message="密码已更新")
