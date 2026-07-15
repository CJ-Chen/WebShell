from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_ROOT = Path("/tmp/webshell-pytest")
TEST_ROOT.mkdir(parents=True, exist_ok=True)
DATABASE_PATH = TEST_ROOT / "webshell.db"
KEY_PATH = TEST_ROOT / "credentials.key"
for path in (DATABASE_PATH, KEY_PATH):
    path.unlink(missing_ok=True)

os.environ["WEBSHELL_DATABASE_URL"] = f"sqlite+aiosqlite:///{DATABASE_PATH}"
os.environ["WEBSHELL_DATA_DIR"] = str(TEST_ROOT)
os.environ["WEBSHELL_CREDENTIAL_KEY_PATH"] = str(KEY_PATH)
os.environ["WEBSHELL_TRUSTED_ORIGINS"] = '["http://testserver"]'

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402


async def _seed_admin() -> None:
    async with SessionLocal() as db:
        db.add(
            User(
                username="admin",
                email="admin@example.com",
                password_hash=hash_password("AdminPassword123!"),
                role="admin",
            )
        )
        await db.commit()


@pytest.fixture(scope="session", autouse=True)
def client():
    with TestClient(app, base_url="http://testserver") as test_client:
        asyncio.run(_seed_admin())
        yield test_client


@pytest.fixture()
def admin_client(client: TestClient):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    csrf = response.json()["csrf_token"]
    client.headers.update({"X-CSRF-Token": csrf, "Origin": "http://testserver"})
    yield client
    client.headers.pop("X-CSRF-Token", None)
    client.headers.pop("Origin", None)
