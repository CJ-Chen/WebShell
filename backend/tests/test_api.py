from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_login_rejects_invalid_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong-password"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


def test_admin_creates_user_and_rule(admin_client: TestClient) -> None:
    user_response = admin_client.post(
        "/api/v1/admin/users",
        json={"username": "researcher", "email": "researcher@example.com", "role": "user"},
    )
    assert user_response.status_code == 201
    assert user_response.json()["temporary_password"]

    rule_response = admin_client.post(
        "/api/v1/admin/destination-rules",
        json={
            "kind": "cidr",
            "value": "10.20.0.0/16",
            "port_min": 22,
            "port_max": 22,
            "enabled": True,
            "description": "compute network",
        },
    )
    assert rule_response.status_code == 201
    assert rule_response.json()["value"] == "10.20.0.0/16"


def test_target_secret_is_not_returned(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/v1/targets",
        json={
            "name": "node-a",
            "host": "10.20.0.10",
            "port": 22,
            "username": "researcher",
            "auth_method": "password",
            "secret": "remote-password",
            "save_secret": True,
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["has_saved_credential"] is True
    assert "secret" not in payload
    assert "remote-password" not in response.text


def test_archived_user_can_be_purged(admin_client: TestClient) -> None:
    users = admin_client.get("/api/v1/admin/users").json()
    researcher = next(user for user in users if user["username"] == "researcher")
    archive = admin_client.post(f"/api/v1/admin/users/{researcher['id']}/archive")
    assert archive.status_code == 200
    purge = admin_client.delete(f"/api/v1/admin/users/{researcher['id']}")
    assert purge.status_code == 200
    remaining = admin_client.get("/api/v1/admin/users").json()
    assert all(user["id"] != researcher["id"] for user in remaining)


def test_csrf_is_required(client: TestClient) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert login.status_code == 200
    response = client.post(
        "/api/v1/targets",
        json={
            "name": "blocked",
            "host": "10.20.0.11",
            "port": 22,
            "username": "user",
            "auth_method": "password",
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
