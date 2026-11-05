"""Resolve encrypted device credentials for one authorized execution."""
from app.database.models import Credential
from app.security.credential_encryption import CredentialEncryptionError, decrypt_credential


def resolve_credential_secret(credential: Credential) -> str:
    return decrypt_credential(
        credential.encrypted_secret,
        credential.encryption_nonce,
        credential.encryption_key_id,
        owner_id=credential.owner_id,
        credential_id=credential.id,
    )
