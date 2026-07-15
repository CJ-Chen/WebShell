from __future__ import annotations

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import AppError
from ..models import EncryptedCredential, TargetHost, User, utcnow
from ..schemas import (
    ConfirmHostKey,
    Message,
    ProbeResult,
    TargetCreate,
    TargetPublic,
    TargetUnlock,
    TargetUpdate,
)
from ..services.audit import record_audit
from ..services.encryption import secret_cache
from ..services.rate_limit import rate_limiter
from ..services.ssh import clear_saved_secret, save_target_secret, ssh_manager


router = APIRouter(prefix="/targets", tags=["targets"])


def target_public(target: TargetHost) -> TargetPublic:
    return TargetPublic(
        id=target.id,
        name=target.name,
        host=target.host,
        port=target.port,
        username=target.username,
        auth_method=target.auth_method,
        default_path=target.default_path,
        host_key_algorithm=target.host_key_algorithm,
        host_key_fingerprint=target.host_key_fingerprint,
        status=target.status,
        last_error=target.last_error,
        last_connected_at=target.last_connected_at,
        has_saved_credential=bool(target.credential_id),
    )


async def owned_target(db: AsyncSession, target_id: str, user_id: int) -> TargetHost:
    target = await db.scalar(
        select(TargetHost).where(TargetHost.id == target_id, TargetHost.owner_id == user_id)
    )
    if not target:
        raise AppError(404, "TARGET_NOT_FOUND", "目标机不存在")
    return target


@router.get("", response_model=List[TargetPublic])
async def list_targets(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> List[TargetPublic]:
    targets = (
        await db.execute(
            select(TargetHost)
            .where(TargetHost.owner_id == user.id)
            .order_by(TargetHost.created_at.desc())
        )
    ).scalars().all()
    return [target_public(target) for target in targets]


@router.post("", response_model=TargetPublic, status_code=201)
async def create_target(
    payload: TargetCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> TargetPublic:
    target = TargetHost(
        owner_id=context.user.id,
        name=payload.name.strip(),
        host=payload.host.strip(),
        port=payload.port,
        username=payload.username.strip(),
        auth_method=payload.auth_method,
        default_path=payload.default_path,
    )
    db.add(target)
    await db.flush()
    if payload.secret:
        persist = payload.save_secret or payload.auth_method == "private_key"
        await save_target_secret(db, target, payload.secret, persist)
    await record_audit(
        db,
        "target.created",
        "target",
        target.id,
        actor_id=context.user.id,
        detail={"host": target.host, "port": target.port},
        request=request,
    )
    await db.commit()
    await db.refresh(target)
    return target_public(target)


@router.patch("/{target_id}", response_model=TargetPublic)
async def update_target(
    target_id: str,
    payload: TargetUpdate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> TargetPublic:
    target = await owned_target(db, target_id, context.user.id)
    values = payload.model_dump(exclude_unset=True)
    identity_changed = any(key in values for key in ("host", "port"))
    for key, value in values.items():
        setattr(target, key, value.strip() if isinstance(value, str) else value)
    if identity_changed:
        target.host_key_algorithm = None
        target.host_key_fingerprint = None
        target.status = "unverified"
    await record_audit(
        db, "target.updated", "target", target.id, actor_id=context.user.id, request=request
    )
    await db.commit()
    await db.refresh(target)
    return target_public(target)


@router.delete("/{target_id}", response_model=Message)
async def delete_target(
    target_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> Message:
    target = await owned_target(db, target_id, context.user.id)
    credential = await db.get(EncryptedCredential, target.credential_id) if target.credential_id else None
    secret_cache.remove(context.user.id, target.id)
    await db.delete(target)
    if credential:
        await db.delete(credential)
    await record_audit(
        db, "target.deleted", "target", target.id, actor_id=context.user.id, request=request
    )
    await db.commit()
    return Message(message="目标机已删除")


@router.post("/{target_id}/unlock", response_model=Message)
async def unlock_target(
    target_id: str,
    payload: TargetUnlock,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> Message:
    target = await owned_target(db, target_id, context.user.id)
    persist = payload.save_secret or target.auth_method == "private_key"
    await save_target_secret(db, target, payload.secret, persist)
    await record_audit(
        db, "target.unlocked", "target", target.id, actor_id=context.user.id, request=request
    )
    await db.commit()
    return Message(message="目标机凭据已更新")


@router.post("/{target_id}/lock", response_model=Message)
async def lock_target(
    target_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> Message:
    target = await owned_target(db, target_id, context.user.id)
    secret_cache.remove(context.user.id, target.id)
    await record_audit(
        db, "target.locked", "target", target.id, actor_id=context.user.id, request=request
    )
    await db.commit()
    return Message(message="临时凭据已清除")


@router.delete("/{target_id}/credential", response_model=Message)
async def forget_credential(
    target_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> Message:
    target = await owned_target(db, target_id, context.user.id)
    await clear_saved_secret(db, target)
    await record_audit(
        db, "target.credential_forgotten", "target", target.id, actor_id=context.user.id, request=request
    )
    await db.commit()
    return Message(message="保存的凭据已删除")


@router.post("/{target_id}/probe", response_model=ProbeResult)
async def probe_target(
    target_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> ProbeResult:
    rate_limiter.check(f"probe:{context.user.id}", 20, 300)
    target = await owned_target(db, target_id, context.user.id)
    try:
        connection, identity, _destination = await ssh_manager.connect(
            db, target, verify_host_key=False
        )
        try:
            sftp = await connection.start_sftp_client()
            home_path = await sftp.realpath(".")
            sftp.exit()
        except Exception:
            home_path = None
        connection.close()
        await connection.wait_closed()
        confirmed = (
            target.host_key_fingerprint == identity.fingerprint
            and target.host_key_algorithm == identity.algorithm
        )
        target.status = "connected" if confirmed else "unverified"
        target.last_error = None
        target.last_connected_at = utcnow()
        await record_audit(
            db,
            "target.probed",
            "target",
            target.id,
            actor_id=context.user.id,
            detail={"confirmed": confirmed},
            request=request,
        )
        await db.commit()
        return ProbeResult(
            fingerprint=identity.fingerprint,
            algorithm=identity.algorithm,
            confirmed=confirmed,
            home_path=str(home_path) if home_path else None,
        )
    except AppError as exc:
        target.status = "error"
        target.last_error = exc.message
        await record_audit(
            db,
            "target.probed",
            "target",
            target.id,
            actor_id=context.user.id,
            outcome="failure",
            detail={"code": exc.code},
            request=request,
        )
        await db.commit()
        raise


@router.post("/{target_id}/confirm-host-key", response_model=TargetPublic)
async def confirm_host_key(
    target_id: str,
    payload: ConfirmHostKey,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> TargetPublic:
    target = await owned_target(db, target_id, context.user.id)
    connection, identity, _destination = await ssh_manager.connect(db, target, verify_host_key=False)
    connection.close()
    await connection.wait_closed()
    if identity.fingerprint != payload.fingerprint or identity.algorithm != payload.algorithm:
        raise AppError(409, "HOST_KEY_RACE", "服务器指纹在确认前发生变化")
    target.host_key_fingerprint = identity.fingerprint
    target.host_key_algorithm = identity.algorithm
    target.status = "connected"
    target.last_error = None
    target.last_connected_at = utcnow()
    await record_audit(
        db,
        "target.host_key_confirmed",
        "target",
        target.id,
        actor_id=context.user.id,
        detail={"fingerprint": identity.fingerprint},
        request=request,
    )
    await db.commit()
    await db.refresh(target)
    return target_public(target)
