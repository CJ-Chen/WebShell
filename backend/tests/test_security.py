from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import DestinationRule
from app.routers.files import normalize_remote_path
from app.routers.terminals import (
    _receive_terminal_input,
    ensure_tmux_session,
    terminal_dimension,
)
from app.security import hash_password, verify_password
from app.schemas import ChangePasswordRequest
from app.services.destination import resolve_destination
from app.services.encryption import cipher


class TerminalMessagesDone(Exception):
    pass


class FakeTerminalWebSocket:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self.messages = iter(messages)

    async def receive_text(self) -> str:
        try:
            return json.dumps(next(self.messages))
        except StopIteration as exc:
            raise TerminalMessagesDone from exc


class FakeTerminalConnection:
    def __init__(self, pane_modes: list[str]) -> None:
        self.commands: list[str] = []
        self.pane_modes = iter(pane_modes)

    async def run(self, command: str, check: bool = False) -> SimpleNamespace:
        self.commands.append(command)
        stdout = next(self.pane_modes, "1\n") if "display-message" in command else ""
        return SimpleNamespace(stdout=stdout)


class FakeTerminalProcess:
    def __init__(self) -> None:
        self.stdin = self
        self.data = bytearray()

    def write(self, data: bytes) -> None:
        self.data.extend(data)


def test_password_hash_round_trip() -> None:
    encoded = hash_password("StrongPassword123!")
    assert encoded != "StrongPassword123!"
    assert verify_password(encoded, "StrongPassword123!")
    assert not verify_password(encoded, "wrong")


def test_password_policy_only_requires_six_characters() -> None:
    payload = ChangePasswordRequest(current_password="old", new_password="123456")
    assert payload.new_password == "123456"
    with pytest.raises(ValidationError):
        ChangePasswordRequest(current_password="old", new_password="12345")


def test_credential_cipher_binds_owner_and_kind() -> None:
    nonce, ciphertext = cipher.encrypt("secret", 7, "password")
    assert cipher.decrypt(nonce, ciphertext, 7, "password") == "secret"
    with pytest.raises(Exception):
        cipher.decrypt(nonce, ciphertext, 8, "password")


def test_remote_path_validation() -> None:
    assert normalize_remote_path("/data/project/../result") == "/data/result"
    with pytest.raises(AppError):
        normalize_remote_path("bad\x00path")


def test_terminal_dimensions_are_clamped() -> None:
    assert terminal_dimension("132", 80, 20, 500) == 132
    assert terminal_dimension("invalid", 80, 20, 500) == 80
    assert terminal_dimension("2", 80, 20, 500) == 20
    assert terminal_dimension("900", 80, 20, 500) == 500


def test_existing_tmux_session_leaves_mouse_for_browser_selection() -> None:
    class Result:
        exit_status = 0

    class Connection:
        def __init__(self) -> None:
            self.commands: list[str] = []

        async def run(self, command: str, check: bool = False):
            self.commands.append(command)
            return Result()

    async def run() -> None:
        connection = Connection()
        await ensure_tmux_session(connection, "ws_test")
        assert any("set-option -g mouse off" in command for command in connection.commands)

    asyncio.run(run())


def test_terminal_history_scroll_exits_copy_mode_at_bottom() -> None:
    async def run() -> None:
        connection = FakeTerminalConnection(["1\n", "0\n"])
        process = FakeTerminalProcess()
        websocket = FakeTerminalWebSocket(
            [
                {"type": "history-scroll", "direction": "up", "lines": 4},
                {"type": "history-scroll", "direction": "down", "lines": 12},
                {"type": "history-scroll", "direction": "down", "lines": 3},
                {"type": "input", "data": "echo ready\n"},
            ]
        )
        with pytest.raises(TerminalMessagesDone):
            await _receive_terminal_input(websocket, process, connection, "ws_test")
        assert connection.commands == [
            "tmux copy-mode -t ws_test; "
            "tmux send-keys -X -t ws_test -N 4 scroll-up; "
            "tmux display-message -p -t ws_test '#{pane_in_mode}'",
            "tmux send-keys -X -t ws_test -N 12 scroll-down-and-cancel; "
            "tmux display-message -p -t ws_test '#{pane_in_mode}'",
        ]
        assert process.stdin.data == b"echo ready\n"

    asyncio.run(run())


def test_terminal_input_cancels_active_history_mode() -> None:
    async def run() -> None:
        connection = FakeTerminalConnection(["1\n"])
        process = FakeTerminalProcess()
        websocket = FakeTerminalWebSocket(
            [
                {"type": "history-scroll", "direction": "up", "lines": 2},
                {"type": "input", "data": "a"},
            ]
        )
        with pytest.raises(TerminalMessagesDone):
            await _receive_terminal_input(websocket, process, connection, "ws_test")
        assert connection.commands[-1] == "tmux send-keys -X -t ws_test cancel"
        assert process.stdin.data == b"a"

    asyncio.run(run())


def test_destination_rules_are_optional_and_system_ranges_stay_blocked() -> None:
    async def run() -> None:
        async with SessionLocal() as db:
            existing = await db.scalar(
                select(DestinationRule).where(DestinationRule.value == "10.20.0.0/16")
            )
            if not existing:
                db.add(
                    DestinationRule(
                        kind="cidr", value="10.20.0.0/16", port_min=22, port_max=22
                    )
                )
                await db.commit()
            result = await resolve_destination(db, "10.20.4.9", 22)
            assert result.connect_host == "10.20.4.9"
            unrestricted = await resolve_destination(db, "10.30.4.9", 22)
            assert unrestricted.connect_host == "10.30.4.9"
            with pytest.raises(AppError) as blocked:
                await resolve_destination(db, "127.0.0.1", 22)
            assert blocked.value.code == "DESTINATION_BLOCKED"

    asyncio.run(run())
