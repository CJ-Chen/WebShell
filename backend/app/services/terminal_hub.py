from __future__ import annotations

import asyncio
from typing import Dict, Tuple

from fastapi import WebSocket


class TerminalHub:
    def __init__(self) -> None:
        self._connections: Dict[str, Tuple[int, WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def register(self, terminal_id: str, user_id: int, websocket: WebSocket) -> bool:
        async with self._lock:
            if terminal_id in self._connections:
                return False
            self._connections[terminal_id] = (user_id, websocket)
            return True

    async def unregister(self, terminal_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            current = self._connections.get(terminal_id)
            if current and current[1] is websocket:
                self._connections.pop(terminal_id, None)

    async def close_user(self, user_id: int, reason: str = "账号状态已变化") -> None:
        async with self._lock:
            sockets = [socket for owner_id, socket in self._connections.values() if owner_id == user_id]
        for socket in sockets:
            try:
                await socket.close(code=4403, reason=reason)
            except RuntimeError:
                pass


terminal_hub = TerminalHub()
