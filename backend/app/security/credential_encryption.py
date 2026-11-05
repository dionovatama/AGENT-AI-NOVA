"""Authenticated encryption for device credentials (AES-256-GCM).

Keyring format:
    CREDENTIAL_ENCRYPTION_KEYS_JSON={"key-v1":"<base64 32-byte key>"}
    CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID=key-v1

Keys must be supplied by deployment secret storage, never by the database.
"""
from __future__ import annotations

import base64
import binascii
import json
import secrets
import uuid
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


class CredentialEncryptionError(RuntimeError):
    """Credential cannot safely be encrypted or decrypted."""


@dataclass(frozen=True)
class EncryptedCredential:
    ciphertext: str
    nonce: str
    key_id: str


def _load_keyring() -> tuple[dict[str, bytes], str]:
    raw = settings.credential_encryption_keys_json
    active_key_id = settings.credential_encryption_active_key_id
    if not raw or not active_key_id:
        raise CredentialEncryptionError(
            "Credential encryption is not configured. Set "
            "CREDENTIAL_ENCRYPTION_KEYS_JSON and CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID."
        )
    try:
        encoded_keys = json.loads(raw)
        if not isinstance(encoded_keys, dict) or not encoded_keys:
            raise ValueError("keyring must be a non-empty JSON object")
        keys: dict[str, bytes] = {}
        for key_id, encoded in encoded_keys.items():
            if not isinstance(key_id, str) or not key_id or not isinstance(encoded, str):
                raise ValueError("invalid keyring entry")
            key = base64.b64decode(encoded, validate=True)
            if len(key) != 32:
                raise ValueError(f"key {key_id!r} must decode to exactly 32 bytes")
            keys[key_id] = key
        if active_key_id not in keys:
            raise ValueError("active key id is not present in keyring")
        return keys, active_key_id
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError) as exc:
        raise CredentialEncryptionError("Invalid credential encryption keyring configuration.") from exc


def _aad(owner_id: uuid.UUID | str, credential_id: uuid.UUID | str) -> bytes:
    return f"nova:credential:v1:{owner_id}:{credential_id}".encode("utf-8")


def encrypt_credential(
    plaintext: str,
    owner_id: uuid.UUID | str,
    credential_id: uuid.UUID | str,
) -> EncryptedCredential:
    if not isinstance(plaintext, str) or not plaintext:
        raise CredentialEncryptionError("Credential secret must not be empty.")
    keys, active_key_id = _load_keyring()
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(keys[active_key_id]).encrypt(
        nonce, plaintext.encode("utf-8"), _aad(owner_id, credential_id)
    )
    return EncryptedCredential(
        ciphertext=base64.b64encode(ciphertext).decode("ascii"),
        nonce=base64.b64encode(nonce).decode("ascii"),
        key_id=active_key_id,
    )


def decrypt_credential(
    ciphertext: str | None,
    nonce: str | None,
    key_id: str | None,
    owner_id: uuid.UUID | str,
    credential_id: uuid.UUID | str,
) -> str:
    if not ciphertext or not nonce or not key_id:
        raise CredentialEncryptionError(
            "Credential is still plaintext/legacy or incomplete. Run the credential migration command."
        )
    keys, _ = _load_keyring()
    key = keys.get(key_id)
    if key is None:
        raise CredentialEncryptionError(
            f"Credential encryption key {key_id!r} is unavailable; restore the key before use."
        )
    try:
        plain = AESGCM(key).decrypt(
            base64.b64decode(nonce, validate=True),
            base64.b64decode(ciphertext, validate=True),
            _aad(owner_id, credential_id),
        )
        return plain.decode("utf-8")
    except (InvalidTag, ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise CredentialEncryptionError(
            "Credential authentication failed; ciphertext, nonce, owner, or credential identity is invalid."
        ) from exc
