import base64
import json
import uuid

import pytest

from app.security.credential_encryption import (
    CredentialEncryptionError,
    decrypt_credential,
    encrypt_credential,
)
from app.config import settings


def _configure_keyring(monkeypatch, key_id="test-v1"):
    key = base64.b64encode(b"T" * 32).decode("ascii")
    monkeypatch.setattr(settings, "credential_encryption_keys_json", json.dumps({key_id: key}))
    monkeypatch.setattr(settings, "credential_encryption_active_key_id", key_id)


def test_encrypt_decrypt_round_trip_and_no_plaintext(monkeypatch):
    _configure_keyring(monkeypatch)
    owner_id, credential_id = uuid.uuid4(), uuid.uuid4()
    secret = "router-password-for-test"
    encrypted = encrypt_credential(secret, owner_id, credential_id)

    assert secret not in encrypted.ciphertext
    assert encrypted.key_id == "test-v1"
    assert decrypt_credential(
        encrypted.ciphertext, encrypted.nonce, encrypted.key_id, owner_id, credential_id
    ) == secret


def test_ciphertext_is_bound_to_owner_and_credential(monkeypatch):
    _configure_keyring(monkeypatch)
    owner_id, credential_id = uuid.uuid4(), uuid.uuid4()
    encrypted = encrypt_credential("secret", owner_id, credential_id)

    with pytest.raises(CredentialEncryptionError):
        decrypt_credential(
            encrypted.ciphertext, encrypted.nonce, encrypted.key_id,
            uuid.uuid4(), credential_id
        )
    with pytest.raises(CredentialEncryptionError):
        decrypt_credential(
            encrypted.ciphertext, encrypted.nonce, encrypted.key_id,
            owner_id, uuid.uuid4()
        )


def test_tampered_ciphertext_is_rejected(monkeypatch):
    _configure_keyring(monkeypatch)
    owner_id, credential_id = uuid.uuid4(), uuid.uuid4()
    encrypted = encrypt_credential("secret", owner_id, credential_id)
    tampered = base64.b64encode(b"tampered-data").decode("ascii")

    with pytest.raises(CredentialEncryptionError):
        decrypt_credential(tampered, encrypted.nonce, encrypted.key_id, owner_id, credential_id)


def test_missing_keyring_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "credential_encryption_keys_json", None)
    monkeypatch.setattr(settings, "credential_encryption_active_key_id", None)

    with pytest.raises(CredentialEncryptionError):
        encrypt_credential("secret", uuid.uuid4(), uuid.uuid4())


def test_legacy_plaintext_row_is_not_used_for_execution(monkeypatch):
    _configure_keyring(monkeypatch)
    with pytest.raises(CredentialEncryptionError):
        decrypt_credential(None, None, None, uuid.uuid4(), uuid.uuid4())


def test_keyring_can_decrypt_old_key_after_active_key_rotation(monkeypatch):
    old_key = base64.b64encode(b"O" * 32).decode("ascii")
    new_key = base64.b64encode(b"N" * 32).decode("ascii")
    monkeypatch.setattr(
        settings,
        "credential_encryption_keys_json",
        json.dumps({"key-v1": old_key, "key-v2": new_key}),
    )
    monkeypatch.setattr(settings, "credential_encryption_active_key_id", "key-v1")
    owner_id, credential_id = uuid.uuid4(), uuid.uuid4()
    old_encrypted = encrypt_credential("rotate-me", owner_id, credential_id)

    monkeypatch.setattr(settings, "credential_encryption_active_key_id", "key-v2")
    assert decrypt_credential(
        old_encrypted.ciphertext, old_encrypted.nonce, old_encrypted.key_id,
        owner_id, credential_id
    ) == "rotate-me"
    new_encrypted = encrypt_credential("rotate-me", owner_id, credential_id)
    assert new_encrypted.key_id == "key-v2"
