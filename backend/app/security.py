from __future__ import annotations

import hashlib
import re
import secrets
import string
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .config import get_settings
from .models import utcnow


password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{2,31}$")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def generate_temporary_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in value) and any(c.isupper() for c in value) and any(c.isdigit() for c in value):
            return value


def generate_session() -> tuple[str, str, datetime, datetime]:
    settings = get_settings()
    now = utcnow()
    return (
        secrets.token_urlsafe(32),
        secrets.token_urlsafe(32),
        now + timedelta(seconds=settings.session_idle_seconds),
        now + timedelta(seconds=settings.session_absolute_seconds),
    )


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
