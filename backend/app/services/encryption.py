from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import get_settings


def generate_key_file(path: Path) -> None:
    if path.exists():
        raise RuntimeError(f"Credential key already exists at {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    key = AESGCM.generate_key(bit_length=256)
    path.write_bytes(base64.urlsafe_b64encode(key))
    os.chmod(path, 0o600)


def _load_or_create_key(path: Path) -> bytes:
    if path.exists():
        raw = path.read_bytes().strip()
        try:
            key = base64.urlsafe_b64decode(raw)
        except Exception as exc:
            raise RuntimeError(f"Invalid credential key at {path}") from exc
        if len(key) != 32:
            raise RuntimeError(f"Credential key at {path} must decode to 32 bytes")
        return key
    if get_settings().is_production:
        raise RuntimeError(f"Credential key is missing at {path}; run the init-key task first")
    generate_key_file(path)
    return base64.urlsafe_b64decode(path.read_bytes().strip())


class CredentialCipher:
    def __init__(self) -> None:
        self._key = _load_or_create_key(get_settings().credential_key_path)
        self._cipher = AESGCM(self._key)

    def encrypt(self, value: str, owner_id: int, kind: str) -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        aad = f"webshell:{owner_id}:{kind}".encode("utf-8")
        return nonce, self._cipher.encrypt(nonce, value.encode("utf-8"), aad)

    def decrypt(self, nonce: bytes, ciphertext: bytes, owner_id: int, kind: str) -> str:
        aad = f"webshell:{owner_id}:{kind}".encode("utf-8")
        return self._cipher.decrypt(nonce, ciphertext, aad).decode("utf-8")


@dataclass
class CachedSecret:
    value: str
    expires_at: float


class SecretCache:
    def __init__(self) -> None:
        self._values: Dict[Tuple[int, str], CachedSecret] = {}

    def put(self, user_id: int, target_id: str, value: str) -> None:
        self._values[(user_id, target_id)] = CachedSecret(
            value=value, expires_at=time.monotonic() + get_settings().secret_cache_seconds
        )

    def get(self, user_id: int, target_id: str) -> Optional[str]:
        item = self._values.get((user_id, target_id))
        if not item:
            return None
        if item.expires_at <= time.monotonic():
            self._values.pop((user_id, target_id), None)
            return None
        return item.value

    def remove(self, user_id: int, target_id: str) -> None:
        self._values.pop((user_id, target_id), None)

    def remove_user(self, user_id: int) -> None:
        for key in [key for key in self._values if key[0] == user_id]:
            self._values.pop(key, None)


cipher = CredentialCipher()
secret_cache = SecretCache()
