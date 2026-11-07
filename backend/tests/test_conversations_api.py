"""Conversation history API tests: authentication and per-account isolation."""
import uuid

from fastapi.testclient import TestClient

from app.database.models import User
from app.database.session import SessionLocal
from app.main import app
from app.security.hashing import create_access_token

client = TestClient(app)


def _headers(label: str) -> dict[str, str]:
    user_id = uuid.uuid4()
    db = SessionLocal()
    try:
        db.add(User(
            id=user_id,
            email=f"{label}-{user_id.hex[:8]}@example.com",
            hashed_password="placeholder_hash",
            is_active=True,
        ))
        db.commit()
    finally:
        db.close()
    token = create_access_token(subject=str(user_id))
    return {"Authorization": f"Bearer {token}"}


def test_conversation_history_is_scoped_to_authenticated_account():
    headers_a = _headers("conversation-a")
    headers_b = _headers("conversation-b")

    created = client.post("/conversations", headers=headers_a, json={"title": "Private chat"})
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    saved = client.post(
        f"/conversations/{conversation_id}/messages",
        headers=headers_a,
        json={"role": "user", "content": "Hello NOVA"},
    )
    assert saved.status_code == 201
    assert saved.json()["content"] == "Hello NOVA"

    own_list = client.get("/conversations", headers=headers_a)
    assert own_list.status_code == 200
    assert any(item["id"] == conversation_id for item in own_list.json())

    other_list = client.get("/conversations", headers=headers_b)
    assert other_list.status_code == 200
    assert all(item["id"] != conversation_id for item in other_list.json())

    # An account must not read, append to, rename, or delete another account's chat.
    assert client.get(f"/conversations/{conversation_id}/messages", headers=headers_b).status_code == 404
    assert client.post(
        f"/conversations/{conversation_id}/messages",
        headers=headers_b,
        json={"role": "assistant", "content": "Unauthorized"},
    ).status_code == 404
    assert client.patch(
        f"/conversations/{conversation_id}",
        headers=headers_b,
        json={"title": "Hijacked"},
    ).status_code == 404
    assert client.delete(f"/conversations/{conversation_id}", headers=headers_b).status_code == 404

    # Owner can still read and delete their own conversation.
    messages = client.get(f"/conversations/{conversation_id}/messages", headers=headers_a)
    assert messages.status_code == 200
    assert len(messages.json()) == 1
    assert client.delete(f"/conversations/{conversation_id}", headers=headers_a).status_code == 204


def test_conversation_endpoints_require_authentication():
    assert client.get("/conversations").status_code == 401
    assert client.post("/conversations", json={"title": "No token"}).status_code == 401
