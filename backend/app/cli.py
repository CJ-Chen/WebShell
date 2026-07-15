from __future__ import annotations

import argparse
import asyncio
import base64
import os
import ipaddress
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import delete, select

from .database import SessionLocal, create_schema
from .models import DestinationRule, User, WebSession
from .security import generate_temporary_password, hash_password


async def create_admin(username: str, email: str, password: str | None) -> None:
    await create_schema()
    if password is not None and len(password) < 6:
        raise SystemExit("Password must contain at least 6 characters")
    temporary = password or generate_temporary_password()
    try:
        normalized_email = validate_email(email, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise SystemExit(f"Invalid email: {exc}") from exc
    async with SessionLocal() as db:
        existing = await db.scalar(select(User).where(User.username == username))
        if existing:
            raise SystemExit(f"User {username} already exists")
        db.add(
            User(
                username=username,
                email=normalized_email.lower(),
                password_hash=hash_password(temporary),
                role="admin",
                must_change_password=password is None,
            )
        )
        await db.commit()
    print(f"Admin created: {username}")
    if password is None:
        print(f"Temporary password: {temporary}")


async def add_cidr(value: str, port: int) -> None:
    await create_schema()
    try:
        normalized = str(ipaddress.ip_network(value, strict=False))
    except ValueError as exc:
        raise SystemExit(f"Invalid CIDR: {value}") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("Port must be between 1 and 65535")
    async with SessionLocal() as db:
        db.add(DestinationRule(kind="cidr", value=normalized, port_min=port, port_max=port))
        await db.commit()
    print(f"Allowed destination: {normalized}:{port}")


async def set_password(username: str, password: str) -> None:
    if len(password) < 6:
        raise SystemExit("Password must contain at least 6 characters")
    await create_schema()
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == username))
        if not user:
            raise SystemExit(f"User {username} does not exist")
        user.password_hash = hash_password(password)
        user.must_change_password = False
        await db.execute(delete(WebSession).where(WebSession.user_id == user.id))
        await db.commit()
    print(f"Password updated: {username}")


def main() -> None:
    parser = argparse.ArgumentParser(description="WebShell administration CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    admin = subparsers.add_parser("create-admin")
    admin.add_argument("--username", required=True)
    admin.add_argument("--email", required=True)
    admin.add_argument("--password")
    cidr = subparsers.add_parser("allow-cidr")
    cidr.add_argument("cidr")
    cidr.add_argument("--port", type=int, default=22)
    init_key = subparsers.add_parser("init-key")
    init_key.add_argument("--path", default=None)
    password = subparsers.add_parser("set-password")
    password.add_argument("--username", required=True)
    password.add_argument("--password", required=True)
    args = parser.parse_args()
    if args.command == "create-admin":
        asyncio.run(create_admin(args.username, args.email, args.password))
    elif args.command == "allow-cidr":
        asyncio.run(add_cidr(args.cidr, args.port))
    elif args.command == "init-key":
        from .config import get_settings

        path = Path(args.path) if args.path else get_settings().credential_key_path
        if path.exists():
            raise SystemExit(f"Credential key already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)))
        os.chmod(path, 0o600)
        print(f"Credential key created: {path}")
    elif args.command == "set-password":
        asyncio.run(set_password(args.username, args.password))


if __name__ == "__main__":
    main()
