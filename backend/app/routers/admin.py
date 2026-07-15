from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..dependencies import AuthContext, require_admin, require_csrf
from ..errors import AppError
from ..models import AuditLog, DestinationRule, User, WebSession, utcnow
from ..schemas import (
    AuditPublic,
    DestinationRuleCreate,
    DestinationRulePublic,
    Message,
    PasswordResetResult,
    UserCreate,
    UserCreateResult,
    UserPublic,
)
from ..security import generate_temporary_password, hash_password
from ..services.audit import record_audit
from ..services.encryption import secret_cache
from ..services.terminal_hub import terminal_hub


router = APIRouter(prefix="/admin", tags=["admin"])


def _validate_rule(payload: DestinationRuleCreate) -> str:
    value = payload.value.strip().lower()
    if payload.kind == "cidr":
        try:
            return str(ipaddress.ip_network(value, strict=False))
        except ValueError as exc:
            raise AppError(400, "INVALID_CIDR", "CIDR 格式无效") from exc
    if value.startswith("*."):
        value = value[2:]
    if not re.fullmatch(r"[a-z0-9.-]+", value) or "." not in value:
        raise AppError(400, "INVALID_DOMAIN", "域名后缀格式无效")
    return value.rstrip(".")


@router.get("/users", response_model=List[UserPublic])
async def list_users(
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> List[UserPublic]:
    users = (await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
    return [UserPublic.model_validate(user) for user in users]


@router.post("/users", response_model=UserCreateResult, status_code=201)
async def create_user(
    payload: UserCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> UserCreateResult:
    if context.user.role != "admin":
        raise AppError(403, "ADMIN_REQUIRED", "需要管理员权限")
    exists = await db.scalar(
        select(func.count(User.id)).where(
            (func.lower(User.username) == payload.username.lower())
            | (func.lower(User.email) == payload.email.lower())
        )
    )
    if exists:
        raise AppError(409, "USER_EXISTS", "用户名或邮箱已存在")
    temporary = payload.password or generate_temporary_password()
    user = User(
        username=payload.username,
        email=payload.email.lower(),
        role=payload.role,
        password_hash=hash_password(temporary),
        must_change_password=payload.password is None,
    )
    db.add(user)
    await db.flush()
    await record_audit(
        db,
        "admin.user_created",
        "user",
        str(user.id),
        actor_id=context.user.id,
        detail={"role": user.role},
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    return UserCreateResult(
        user=UserPublic.model_validate(user),
        temporary_password=temporary if payload.password is None else None,
    )


async def _set_user_status(
    user_id: int,
    status: str,
    action: str,
    request: Request,
    context: AuthContext,
    db: AsyncSession,
) -> Message:
    if context.user.role != "admin":
        raise AppError(403, "ADMIN_REQUIRED", "需要管理员权限")
    user = await db.get(User, user_id)
    if not user:
        raise AppError(404, "USER_NOT_FOUND", "用户不存在")
    if user.id == context.user.id and status != "active":
        raise AppError(400, "SELF_DISABLE_FORBIDDEN", "不能停用当前管理员账号")
    user.status = status
    if status == "archived":
        user.archived_at = utcnow()
    if status != "active":
        await db.execute(delete(WebSession).where(WebSession.user_id == user.id))
        secret_cache.remove_user(user.id)
        await terminal_hub.close_user(user.id)
    await record_audit(
        db, action, "user", str(user.id), actor_id=context.user.id, request=request
    )
    await db.commit()
    return Message(message="用户状态已更新")


@router.post("/users/{user_id}/disable", response_model=Message)
async def disable_user(user_id: int, request: Request, context: AuthContext = Depends(require_csrf), db: AsyncSession = Depends(get_db)) -> Message:
    return await _set_user_status(user_id, "disabled", "admin.user_disabled", request, context, db)


@router.post("/users/{user_id}/enable", response_model=Message)
async def enable_user(user_id: int, request: Request, context: AuthContext = Depends(require_csrf), db: AsyncSession = Depends(get_db)) -> Message:
    return await _set_user_status(user_id, "active", "admin.user_enabled", request, context, db)


@router.post("/users/{user_id}/archive", response_model=Message)
async def archive_user(user_id: int, request: Request, context: AuthContext = Depends(require_csrf), db: AsyncSession = Depends(get_db)) -> Message:
    return await _set_user_status(user_id, "archived", "admin.user_archived", request, context, db)


@router.post("/users/{user_id}/reset-password", response_model=PasswordResetResult)
async def reset_password(
    user_id: int,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> PasswordResetResult:
    if context.user.role != "admin":
        raise AppError(403, "ADMIN_REQUIRED", "需要管理员权限")
    user = await db.get(User, user_id)
    if not user:
        raise AppError(404, "USER_NOT_FOUND", "用户不存在")
    temporary = generate_temporary_password()
    user.password_hash = hash_password(temporary)
    user.must_change_password = True
    await db.execute(delete(WebSession).where(WebSession.user_id == user.id))
    secret_cache.remove_user(user.id)
    await record_audit(
        db,
        "admin.password_reset",
        "user",
        str(user.id),
        actor_id=context.user.id,
        request=request,
    )
    await db.commit()
    return PasswordResetResult(temporary_password=temporary)


@router.delete("/users/{user_id}", response_model=Message)
async def purge_user(
    user_id: int,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> Message:
    if context.user.role != "admin":
        raise AppError(403, "ADMIN_REQUIRED", "需要管理员权限")
    user = await db.get(User, user_id)
    if not user:
        raise AppError(404, "USER_NOT_FOUND", "用户不存在")
    if user.id == context.user.id:
        raise AppError(400, "SELF_DELETE_FORBIDDEN", "不能删除当前管理员账号")
    if user.status != "archived":
        raise AppError(409, "USER_NOT_ARCHIVED", "用户必须先归档才能永久删除")
    secret_cache.remove_user(user.id)
    await terminal_hub.close_user(user.id)
    await record_audit(
        db,
        "admin.user_purged",
        "user",
        str(user.id),
        actor_id=context.user.id,
        request=request,
    )
    await db.delete(user)
    await db.commit()
    return Message(message="用户及其面板数据已永久删除")


@router.get("/destination-rules", response_model=List[DestinationRulePublic])
async def list_rules(
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> List[DestinationRulePublic]:
    rules = (await db.execute(select(DestinationRule).order_by(DestinationRule.id))).scalars().all()
    return [DestinationRulePublic.model_validate(rule) for rule in rules]


@router.post("/destination-rules", response_model=DestinationRulePublic, status_code=201)
async def create_rule(
    payload: DestinationRuleCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> DestinationRulePublic:
    if context.user.role != "admin":
        raise AppError(403, "ADMIN_REQUIRED", "需要管理员权限")
    value = _validate_rule(payload)
    rule = DestinationRule(
        kind=payload.kind,
        value=value,
        port_min=payload.port_min,
        port_max=payload.port_max,
        enabled=payload.enabled,
        description=payload.description,
    )
    db.add(rule)
    await db.flush()
    await record_audit(
        db,
        "admin.destination_rule_created",
        "destination_rule",
        str(rule.id),
        actor_id=context.user.id,
        detail={"kind": rule.kind, "value": rule.value},
        request=request,
    )
    await db.commit()
    await db.refresh(rule)
    return DestinationRulePublic.model_validate(rule)


@router.delete("/destination-rules/{rule_id}", response_model=Message)
async def delete_rule(
    rule_id: int,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> Message:
    if context.user.role != "admin":
        raise AppError(403, "ADMIN_REQUIRED", "需要管理员权限")
    rule = await db.get(DestinationRule, rule_id)
    if not rule:
        raise AppError(404, "RULE_NOT_FOUND", "规则不存在")
    await db.delete(rule)
    await record_audit(
        db,
        "admin.destination_rule_deleted",
        "destination_rule",
        str(rule_id),
        actor_id=context.user.id,
        request=request,
    )
    await db.commit()
    return Message(message="规则已删除")


@router.get("/audit-logs", response_model=List[AuditPublic])
async def list_audit_logs(
    limit: int = 100,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> List[AuditPublic]:
    limit = max(1, min(limit, 500))
    logs = (
        await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    ).scalars().all()
    return [AuditPublic.model_validate(log) for log in logs]
