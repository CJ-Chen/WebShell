from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import asyncssh
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..errors import AppError
from ..models import EncryptedCredential, TargetHost
from .destination import ResolvedDestination, resolve_destination
from .encryption import cipher, secret_cache


@dataclass(frozen=True)
class ServerIdentity:
    algorithm: str
    fingerprint: str


def _friendly_ssh_error(exc: Exception) -> AppError:
    if isinstance(exc, (asyncssh.PermissionDenied, asyncssh.KeyImportError)):
        return AppError(401, "SSH_AUTH_FAILED", "SSH 认证失败，请检查用户名和凭据")
    if isinstance(exc, (asyncssh.ConnectionLost, asyncssh.DisconnectError)):
        return AppError(502, "SSH_CONNECTION_LOST", "SSH 连接已断开")
    return AppError(502, "SSH_CONNECT_FAILED", "无法连接目标服务器")


async def load_target_secret(db: AsyncSession, target: TargetHost) -> str:
    cached = secret_cache.get(target.owner_id, target.id)
    if cached is not None:
        return cached
    if not target.credential_id:
        raise AppError(423, "TARGET_LOCKED", "请先输入 SSH 凭据解锁目标机")
    credential = await db.get(EncryptedCredential, target.credential_id)
    if not credential or credential.owner_id != target.owner_id:
        raise AppError(423, "TARGET_LOCKED", "目标机凭据不可用")
    try:
        return cipher.decrypt(
            credential.nonce, credential.ciphertext, credential.owner_id, credential.kind
        )
    except Exception as exc:
        raise AppError(500, "CREDENTIAL_DECRYPT_FAILED", "无法解密目标机凭据") from exc


async def save_target_secret(
    db: AsyncSession, target: TargetHost, secret: str, persist: bool
) -> None:
    secret_cache.put(target.owner_id, target.id, secret)
    if not persist:
        return
    nonce, ciphertext = cipher.encrypt(secret, target.owner_id, target.auth_method)
    credential: Optional[EncryptedCredential] = None
    if target.credential_id:
        credential = await db.get(EncryptedCredential, target.credential_id)
    if credential:
        credential.kind = target.auth_method
        credential.nonce = nonce
        credential.ciphertext = ciphertext
    else:
        credential = EncryptedCredential(
            owner_id=target.owner_id,
            kind=target.auth_method,
            nonce=nonce,
            ciphertext=ciphertext,
        )
        db.add(credential)
        await db.flush()
        target.credential_id = credential.id


async def clear_saved_secret(db: AsyncSession, target: TargetHost) -> None:
    secret_cache.remove(target.owner_id, target.id)
    if target.credential_id:
        credential = await db.get(EncryptedCredential, target.credential_id)
        target.credential_id = None
        await db.flush()
        if credential:
            await db.delete(credential)


class SSHManager:
    async def connect(
        self,
        db: AsyncSession,
        target: TargetHost,
        verify_host_key: bool = True,
    ) -> tuple[asyncssh.SSHClientConnection, ServerIdentity, ResolvedDestination]:
        secret = await load_target_secret(db, target)
        destination = await resolve_destination(db, target.host, target.port)
        options = {
            "host": destination.connect_host,
            "port": target.port,
            "username": target.username,
            "known_hosts": None,
            "agent_path": None,
            "login_timeout": get_settings().ssh_connect_timeout,
            "keepalive_interval": get_settings().ssh_keepalive_seconds,
        }
        if target.auth_method == "password":
            options["password"] = secret
            options["client_keys"] = None
        elif target.auth_method == "private_key":
            try:
                key = asyncssh.import_private_key(secret)
            except Exception as exc:
                raise AppError(400, "INVALID_PRIVATE_KEY", "SSH 私钥格式无效或仍受口令保护") from exc
            options["client_keys"] = [key]
        else:
            raise AppError(400, "INVALID_AUTH_METHOD", "不支持的 SSH 认证方式")
        try:
            connection = await asyncssh.connect(**options)
            server_key = connection.get_server_host_key()
            identity = ServerIdentity(
                algorithm=server_key.get_algorithm(),
                fingerprint=server_key.get_fingerprint("sha256"),
            )
        except AppError:
            raise
        except Exception as exc:
            raise _friendly_ssh_error(exc) from exc

        if verify_host_key:
            if not target.host_key_fingerprint:
                connection.close()
                await connection.wait_closed()
                raise AppError(
                    409,
                    "HOST_KEY_UNCONFIRMED",
                    "请先确认目标服务器主机指纹",
                    detail=identity.fingerprint,
                )
            if (
                target.host_key_fingerprint != identity.fingerprint
                or target.host_key_algorithm != identity.algorithm
            ):
                connection.close()
                await connection.wait_closed()
                raise AppError(
                    409,
                    "HOST_KEY_CHANGED",
                    "目标服务器主机指纹已变化，连接已阻止",
                    detail=identity.fingerprint,
                )
        return connection, identity, destination


ssh_manager = SSHManager()
