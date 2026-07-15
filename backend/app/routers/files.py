from __future__ import annotations

import mimetypes
import base64
import posixpath
import stat
import uuid
from datetime import datetime
from typing import AsyncIterator
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..dependencies import AuthContext, get_current_user, require_csrf
from ..errors import AppError
from ..models import User
from ..schemas import (
    FileDeleteRequest,
    FileItem,
    FileList,
    FileMoveRequest,
    FilePathRequest,
    Message,
    PreviewResult,
)
from ..services.audit import record_audit
from ..services.ssh import ssh_manager
from .targets import owned_target


router = APIRouter(prefix="/files", tags=["files"])


def normalize_remote_path(path: str) -> str:
    value = path.strip()
    if not value or "\x00" in value or any(ord(char) < 32 for char in value):
        raise AppError(400, "INVALID_PATH", "远端路径格式无效")
    normalized = posixpath.normpath(value)
    if normalized == "//":
        normalized = "/"
    return normalized


def file_type(permissions: int | None) -> str:
    if permissions is None:
        return "other"
    if stat.S_ISDIR(permissions):
        return "directory"
    if stat.S_ISREG(permissions):
        return "file"
    if stat.S_ISLNK(permissions):
        return "symlink"
    return "other"


def map_sftp_error(exc: Exception) -> AppError:
    name = exc.__class__.__name__.lower()
    if "nosuchfile" in name or "notfound" in name:
        return AppError(404, "REMOTE_PATH_NOT_FOUND", "远端文件或目录不存在")
    if "permission" in name:
        return AppError(403, "REMOTE_PERMISSION_DENIED", "目标账号无权执行该文件操作")
    return AppError(502, "SFTP_FAILED", "远端文件操作失败")


async def _open_sftp(db: AsyncSession, target_id: str, user_id: int):
    target = await owned_target(db, target_id, user_id)
    connection, _identity, _destination = await ssh_manager.connect(db, target)
    try:
        sftp = await connection.start_sftp_client()
    except Exception as exc:
        connection.close()
        await connection.wait_closed()
        raise AppError(502, "SFTP_UNAVAILABLE", "目标服务器不支持 SFTP") from exc
    return target, connection, sftp


@router.get("", response_model=FileList)
async def list_files(
    target_id: str,
    path: str = ".",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileList:
    target, connection, sftp = await _open_sftp(db, target_id, user.id)
    remote_path = normalize_remote_path(path or target.default_path or ".")
    try:
        home = str(await sftp.realpath("."))
        resolved = str(await sftp.realpath(remote_path))
        items = []
        async for entry in sftp.scandir(resolved):
            attrs = entry.attrs
            modified = (
                datetime.fromtimestamp(attrs.mtime) if attrs.mtime is not None else None
            )
            items.append(
                FileItem(
                    name=entry.filename,
                    path=posixpath.join(resolved, entry.filename),
                    type=file_type(attrs.permissions),
                    size=attrs.size or 0,
                    modified_at=modified,
                    permissions=attrs.permissions,
                )
            )
        items.sort(key=lambda item: (item.type != "directory", item.name.lower()))
        return FileList(path=resolved, home_path=home, items=items)
    except AppError:
        raise
    except Exception as exc:
        raise map_sftp_error(exc) from exc
    finally:
        sftp.exit()
        connection.close()
        await connection.wait_closed()


@router.post("/mkdir", response_model=Message)
async def create_directory(
    target_id: str,
    payload: FilePathRequest,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> Message:
    _target, connection, sftp = await _open_sftp(db, target_id, context.user.id)
    path = normalize_remote_path(payload.path)
    try:
        await sftp.mkdir(path)
        await record_audit(
            db,
            "file.mkdir",
            "target",
            target_id,
            actor_id=context.user.id,
            detail={"path": path},
            request=request,
        )
        await db.commit()
        return Message(message="目录已创建")
    except Exception as exc:
        raise map_sftp_error(exc) from exc
    finally:
        sftp.exit()
        connection.close()
        await connection.wait_closed()


@router.post("/move", response_model=Message)
async def move_file(
    target_id: str,
    payload: FileMoveRequest,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> Message:
    _target, connection, sftp = await _open_sftp(db, target_id, context.user.id)
    source = normalize_remote_path(payload.source)
    destination = normalize_remote_path(payload.destination)
    try:
        await sftp.rename(source, destination)
        await record_audit(
            db,
            "file.moved",
            "target",
            target_id,
            actor_id=context.user.id,
            detail={"source": source, "destination": destination},
            request=request,
        )
        await db.commit()
        return Message(message="文件已移动")
    except Exception as exc:
        raise map_sftp_error(exc) from exc
    finally:
        sftp.exit()
        connection.close()
        await connection.wait_closed()


async def _remove_recursive(sftp, path: str) -> None:
    attrs = await sftp.lstat(path)
    if attrs.permissions is not None and stat.S_ISDIR(attrs.permissions):
        async for entry in sftp.scandir(path):
            if entry.filename in (".", ".."):
                continue
            await _remove_recursive(sftp, posixpath.join(path, entry.filename))
        await sftp.rmdir(path)
    else:
        await sftp.remove(path)


@router.post("/delete", response_model=Message)
async def delete_file(
    target_id: str,
    payload: FileDeleteRequest,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> Message:
    _target, connection, sftp = await _open_sftp(db, target_id, context.user.id)
    path = normalize_remote_path(payload.path)
    try:
        attrs = await sftp.lstat(path)
        is_directory = attrs.permissions is not None and stat.S_ISDIR(attrs.permissions)
        if is_directory and not payload.recursive:
            await sftp.rmdir(path)
        elif is_directory:
            await _remove_recursive(sftp, path)
        else:
            await sftp.remove(path)
        await record_audit(
            db,
            "file.deleted",
            "target",
            target_id,
            actor_id=context.user.id,
            detail={"path": path, "recursive": payload.recursive},
            request=request,
        )
        await db.commit()
        return Message(message="文件已删除")
    except Exception as exc:
        raise map_sftp_error(exc) from exc
    finally:
        sftp.exit()
        connection.close()
        await connection.wait_closed()


@router.get("/preview", response_model=PreviewResult)
async def preview_file(
    target_id: str,
    path: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PreviewResult:
    _target, connection, sftp = await _open_sftp(db, target_id, user.id)
    remote_path = normalize_remote_path(path)
    mime_type = mimetypes.guess_type(remote_path)[0] or "application/octet-stream"
    image_allowed = mime_type in {"image/png", "image/jpeg", "image/gif", "image/webp"}
    text_allowed = mime_type.startswith("text/") or posixpath.splitext(remote_path)[1].lower() in {
        ".json", ".yaml", ".yml", ".csv", ".tsv", ".log", ".md", ".py", ".r", ".sh"
    }
    if not text_allowed and not image_allowed:
        sftp.exit()
        connection.close()
        await connection.wait_closed()
        raise AppError(415, "PREVIEW_UNSUPPORTED", "该文件类型不支持在线文本预览")
    try:
        attrs = await sftp.stat(remote_path)
        limit = get_settings().max_preview_bytes
        remote = await sftp.open(remote_path, "rb")
        try:
            data = await remote.read(limit + 1)
        finally:
            await remote.close()
        truncated = len(data) > limit or (attrs.size is not None and attrs.size > limit)
        payload = data[:limit]
        return PreviewResult(
            path=remote_path,
            mime_type=mime_type,
            content=(
                base64.b64encode(payload).decode("ascii")
                if image_allowed
                else payload.decode("utf-8", errors="replace")
            ),
            truncated=truncated,
            encoding="base64" if image_allowed else "text",
        )
    except Exception as exc:
        raise map_sftp_error(exc) from exc
    finally:
        sftp.exit()
        connection.close()
        await connection.wait_closed()


@router.post("/upload", response_model=Message)
async def upload_file(
    request: Request,
    target_id: str = Form(...),
    path: str = Form(...),
    upload: UploadFile = File(...),
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> Message:
    _target, connection, sftp = await _open_sftp(db, target_id, context.user.id)
    destination = normalize_remote_path(path)
    temporary = f"{destination}.webshell-upload-{uuid.uuid4().hex}"
    total = 0
    try:
        remote = await sftp.open(temporary, "wb")
        try:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > get_settings().max_upload_bytes:
                    raise AppError(413, "UPLOAD_TOO_LARGE", "上传文件超过允许大小")
                await remote.write(chunk)
        finally:
            await remote.close()
        await sftp.rename(temporary, destination)
        await record_audit(
            db,
            "file.uploaded",
            "target",
            target_id,
            actor_id=context.user.id,
            detail={"path": destination, "size": total},
            request=request,
        )
        await db.commit()
        return Message(message="文件上传完成")
    except AppError:
        try:
            await sftp.remove(temporary)
        except Exception:
            pass
        raise
    except Exception as exc:
        try:
            await sftp.remove(temporary)
        except Exception:
            pass
        raise map_sftp_error(exc) from exc
    finally:
        await upload.close()
        sftp.exit()
        connection.close()
        await connection.wait_closed()


@router.get("/download")
async def download_file(
    target_id: str,
    path: str,
    range_header: str | None = Header(default=None, alias="Range"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _target, connection, sftp = await _open_sftp(db, target_id, user.id)
    remote_path = normalize_remote_path(path)
    try:
        attrs = await sftp.stat(remote_path)
        size = attrs.size or 0
        start, end = 0, max(0, size - 1)
        status_code = 200
        if range_header and range_header.startswith("bytes="):
            raw_start, _, raw_end = range_header[6:].partition("-")
            try:
                start = int(raw_start) if raw_start else 0
                end = int(raw_end) if raw_end else end
            except ValueError as exc:
                raise AppError(416, "INVALID_RANGE", "下载范围无效") from exc
            if start < 0 or end < start or end >= size:
                raise AppError(416, "INVALID_RANGE", "下载范围无效")
            status_code = 206
        remote = await sftp.open(remote_path, "rb")
        await remote.seek(start)
    except AppError:
        sftp.exit()
        connection.close()
        await connection.wait_closed()
        raise
    except Exception as exc:
        sftp.exit()
        connection.close()
        await connection.wait_closed()
        raise map_sftp_error(exc) from exc

    async def stream() -> AsyncIterator[bytes]:
        remaining = end - start + 1
        try:
            while remaining > 0:
                chunk = await remote.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        finally:
            await remote.close()
            sftp.exit()
            connection.close()
            await connection.wait_closed()

    filename = posixpath.basename(remote_path) or "download"
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        stream(), status_code=status_code, media_type="application/octet-stream", headers=headers
    )
