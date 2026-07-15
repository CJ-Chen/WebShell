from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import List
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import SessionLocal, get_db
from ..dependencies import AuthContext, authenticate_token, get_current_user, require_csrf
from ..errors import AppError
from ..models import TargetHost, TerminalSession, User, utcnow
from ..schemas import Message, TerminalCreate, TerminalPublic, TerminalUpdate
from ..services.audit import record_audit
from ..services.ssh import ssh_manager
from ..services.terminal_hub import terminal_hub
from .targets import owned_target


router = APIRouter(prefix="/terminals", tags=["terminals"])


def terminal_dimension(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


async def owned_terminal(db: AsyncSession, terminal_id: str, user_id: int) -> TerminalSession:
    terminal = await db.scalar(
        select(TerminalSession).where(
            TerminalSession.id == terminal_id, TerminalSession.owner_id == user_id
        )
    )
    if not terminal:
        raise AppError(404, "TERMINAL_NOT_FOUND", "终端不存在")
    return terminal


async def ensure_tmux_session(connection, session_name: str) -> None:
    history_limit = max(2_000, min(get_settings().tmux_history_limit, 500_000))
    existing = await connection.run(
        f"tmux has-session -t {session_name}", check=False
    )
    if existing.exit_status == 0:
        await connection.run(
            f"tmux set-option -g history-limit {history_limit} "
            "\\; set-option -g mouse off",
            check=False,
        )
        return
    created = await connection.run(
        "tmux start-server "
        f"\\; set-option -g history-limit {history_limit} "
        "\\; set-option -g mouse off "
        f"\\; new-session -d -s {session_name}",
        check=False,
    )
    if created.exit_status != 0:
        raise AppError(502, "TMUX_CREATE_FAILED", "无法在目标服务器创建 tmux 会话")


@router.get("", response_model=List[TerminalPublic])
async def list_terminals(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> List[TerminalPublic]:
    terminals = (
        await db.execute(
            select(TerminalSession)
            .where(TerminalSession.owner_id == user.id)
            .order_by(TerminalSession.created_at)
        )
    ).scalars().all()
    return [TerminalPublic.model_validate(item) for item in terminals]


@router.post("", response_model=TerminalPublic, status_code=201)
async def create_terminal(
    payload: TerminalCreate,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> TerminalPublic:
    count = await db.scalar(
        select(func.count(TerminalSession.id)).where(TerminalSession.owner_id == context.user.id)
    )
    if count >= get_settings().max_terminals_per_user:
        raise AppError(409, "TERMINAL_LIMIT", "已达到终端数量上限")
    target = await owned_target(db, payload.target_id, context.user.id)
    terminal_id = str(uuid.uuid4())
    remote_session_name = f"ws_{terminal_id.replace('-', '')}"
    connection, _identity, _destination = await ssh_manager.connect(db, target)
    try:
        result = await connection.run("command -v tmux >/dev/null 2>&1", check=False)
        persistence_mode = "tmux" if result.exit_status == 0 else "shell"
        if persistence_mode == "tmux":
            await ensure_tmux_session(connection, remote_session_name)
    finally:
        connection.close()
        await connection.wait_closed()
    terminal = TerminalSession(
        id=terminal_id,
        owner_id=context.user.id,
        target_id=target.id,
        name=payload.name.strip(),
        remote_session_name=remote_session_name,
        persistence_mode=persistence_mode,
    )
    db.add(terminal)
    await record_audit(
        db,
        "terminal.created",
        "terminal",
        terminal.id,
        actor_id=context.user.id,
        detail={"target_id": target.id, "mode": persistence_mode},
        request=request,
    )
    await db.commit()
    await db.refresh(terminal)
    return TerminalPublic.model_validate(terminal)


@router.patch("/{terminal_id}", response_model=TerminalPublic)
async def rename_terminal(
    terminal_id: str,
    payload: TerminalUpdate,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> TerminalPublic:
    terminal = await owned_terminal(db, terminal_id, context.user.id)
    terminal.name = payload.name.strip()
    await db.commit()
    await db.refresh(terminal)
    return TerminalPublic.model_validate(terminal)


@router.delete("/{terminal_id}", response_model=Message)
async def delete_terminal(
    terminal_id: str,
    request: Request,
    context: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> Message:
    terminal = await owned_terminal(db, terminal_id, context.user.id)
    target = await owned_target(db, terminal.target_id, context.user.id)
    if terminal.persistence_mode == "tmux":
        connection, _identity, _destination = await ssh_manager.connect(db, target)
        try:
            await connection.run(
                f"tmux kill-session -t {terminal.remote_session_name}", check=False
            )
        finally:
            connection.close()
            await connection.wait_closed()
    await db.delete(terminal)
    await record_audit(
        db,
        "terminal.deleted",
        "terminal",
        terminal.id,
        actor_id=context.user.id,
        request=request,
    )
    await db.commit()
    return Message(message="终端已删除")


def _websocket_origin_allowed(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return False
    normalized = origin.rstrip("/")
    if normalized in {item.rstrip("/") for item in get_settings().trusted_origins}:
        return True
    try:
        return urlsplit(origin).netloc.lower() == websocket.headers.get("host", "").lower()
    except ValueError:
        return False


async def _receive_terminal_input(
    websocket: WebSocket,
    process,
    connection,
    tmux_session: str | None,
) -> None:
    history_active = False
    while True:
        message = await websocket.receive_text()
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            continue
        message_type = payload.get("type")
        if message_type == "input":
            data = str(payload.get("data", ""))
            if history_active and tmux_session:
                await connection.run(
                    f"tmux send-keys -X -t {tmux_session} cancel", check=False
                )
                history_active = False
                if data in {"q", "\x1b"}:
                    continue
            process.stdin.write(data.encode("utf-8"))
        elif message_type == "resize":
            cols = max(20, min(int(payload.get("cols", 80)), 500))
            rows = max(5, min(int(payload.get("rows", 24)), 200))
            process.change_terminal_size(cols, rows)
        elif message_type == "history-scroll" and tmux_session:
            direction = payload.get("direction")
            if direction not in {"up", "down"}:
                continue
            lines = max(1, min(int(payload.get("lines", 3)), 20))
            if not history_active:
                if direction == "down":
                    continue
                await connection.run(
                    f"tmux copy-mode -t {tmux_session}", check=False
                )
                history_active = True
            await connection.run(
                f"tmux send-keys -X -t {tmux_session} -N {lines} scroll-{direction}",
                check=False,
            )


async def _send_terminal_output(websocket: WebSocket, process) -> None:
    while True:
        data = await process.stdout.read(32768)
        if not data:
            return
        await websocket.send_bytes(data)


@router.websocket("/ws/{terminal_id}")
async def terminal_websocket(websocket: WebSocket, terminal_id: str) -> None:
    if not _websocket_origin_allowed(websocket):
        await websocket.close(code=4403, reason="Invalid origin")
        return
    async with SessionLocal() as db:
        initial_cols = terminal_dimension(websocket.query_params.get("cols"), 80, 20, 500)
        initial_rows = terminal_dimension(websocket.query_params.get("rows"), 24, 5, 200)
        try:
            context = await authenticate_token(
                db, websocket.cookies.get(get_settings().session_cookie)
            )
            terminal = await owned_terminal(db, terminal_id, context.user.id)
            target = await owned_target(db, terminal.target_id, context.user.id)
        except AppError as exc:
            await websocket.close(code=4401 if exc.status_code == 401 else 4403, reason=exc.message)
            return
        terminal_pk = terminal.id
        terminal_mode = terminal.persistence_mode
        remote_session_name = terminal.remote_session_name
        if not await terminal_hub.register(terminal_pk, context.user.id, websocket):
            await websocket.close(code=4429, reason="终端已在其他窗口连接")
            return
        await websocket.accept()
        connection = None
        process = None
        try:
            await websocket.send_json(
                {"type": "status", "status": "connecting", "mode": terminal_mode}
            )
            connection, _identity, _destination = await ssh_manager.connect(db, target)
            command = None
            if terminal_mode == "tmux":
                await ensure_tmux_session(connection, remote_session_name)
                command = f"tmux attach-session -t {remote_session_name}"
            process = await connection.create_process(
                command,
                term_type="xterm-256color",
                term_size=(initial_cols, initial_rows),
                encoding=None,
            )
            terminal.status = "connected"
            terminal.last_connected_at = utcnow()
            await db.commit()
            await websocket.send_json(
                {"type": "status", "status": "connected", "mode": terminal_mode}
            )
            input_task = asyncio.create_task(
                _receive_terminal_input(
                    websocket,
                    process,
                    connection,
                    remote_session_name if terminal_mode == "tmux" else None,
                )
            )
            output_task = asyncio.create_task(_send_terminal_output(websocket, process))
            done, pending = await asyncio.wait(
                {input_task, output_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exception = task.exception()
                if exception and not isinstance(exception, WebSocketDisconnect):
                    raise exception
        except WebSocketDisconnect:
            pass
        except AppError as exc:
            try:
                await websocket.send_json({"type": "error", "code": exc.code, "message": exc.message})
            except RuntimeError:
                pass
        except Exception:
            try:
                await websocket.send_json(
                    {"type": "error", "code": "TERMINAL_FAILED", "message": "终端连接已中断"}
                )
            except RuntimeError:
                pass
        finally:
            try:
                await db.execute(
                    update(TerminalSession)
                    .where(TerminalSession.id == terminal_pk)
                    .values(status="ready")
                )
                await db.commit()
            except Exception:
                await db.rollback()
            if process:
                process.close()
            if connection:
                connection.close()
                await connection.wait_closed()
            await terminal_hub.unregister(terminal_pk, websocket)
            try:
                await websocket.close()
            except RuntimeError:
                pass
