"""
Basic tests Milestone 1.

Catatan: test register/login membutuhkan koneksi PostgreSQL aktif
sesuai DATABASE_URL di .env. Jika DB belum tersedia, jalankan minimal
test_health_check terlebih dahulu untuk verifikasi service hidup.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "N.O.V.A"


@pytest.mark.integration
def test_register_and_login_flow():
    """
    Membutuhkan PostgreSQL aktif. Tandai sebagai integration test
    agar dapat dipisah dari unit test murni jika diperlukan.
    """
    unique_email = f"test-{uuid.uuid4().hex[:8]}@example.com"
    password = "SecurePass123"

    # Register
    register_response = client.post(
        "/auth/register",
        json={"email": unique_email, "password": password},
    )
    assert register_response.status_code == 201
    body = register_response.json()
    assert body["email"] == unique_email
    assert "hashed_password" not in body  # password hash tidak boleh bocor di response

    # Login
    login_response = client.post(
        "/auth/login",
        json={"email": unique_email, "password": password},
    )
    assert login_response.status_code == 200
    token_body = login_response.json()
    assert "access_token" in token_body
    assert token_body["token_type"] == "bearer"

    # Login dengan password salah harus ditolak
    wrong_login = client.post(
        "/auth/login",
        json={"email": unique_email, "password": "WrongPassword"},
    )
    assert wrong_login.status_code == 401
