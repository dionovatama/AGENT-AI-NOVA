"""One-time migration of legacy plaintext credential rows to AES-256-GCM.

Run from backend/:
    python -m app.security.migrate_credentials --dry-run
    python -m app.security.migrate_credentials --apply

The command requires the active keyring environment variables. Keep a verified
database backup before using --apply. It never prints secret values.
"""
from __future__ import annotations

import argparse
import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database.models import Credential
from app.database.session import SessionLocal
from app.security.credential_encryption import CredentialEncryptionError, decrypt_credential, encrypt_credential
from app.config import settings

logger = logging.getLogger("nova.security.credential_migration")


def migrate(db: Session, *, apply: bool, rewrap: bool = False) -> tuple[int, int]:
    if rewrap:
        pending = (
            db.query(Credential)
            .filter(
                Credential.encrypted_secret.is_not(None),
                or_(
                    Credential.encryption_key_id != settings.credential_encryption_active_key_id,
                    Credential.encryption_key_id.is_(None),
                ),
            )
            .yield_per(100)
        )
    else:
        pending = (
            db.query(Credential)
            .filter(
                Credential.encrypted_secret.is_(None),
                Credential.secret_reference.is_not(None),
            )
            .yield_per(100)
        )

    migrated = 0
    for credential in pending:
        if rewrap:
            plaintext = decrypt_credential(
                credential.encrypted_secret,
                credential.encryption_nonce,
                credential.encryption_key_id,
                owner_id=credential.owner_id,
                credential_id=credential.id,
            )
        else:
            plaintext = credential.secret_reference

        encrypted = encrypt_credential(
            plaintext,
            owner_id=credential.owner_id,
            credential_id=credential.id,
        )
        if apply:
            credential.encrypted_secret = encrypted.ciphertext
            credential.encryption_nonce = encrypted.nonce
            credential.encryption_key_id = encrypted.key_id
            if not rewrap:
                # Clear plaintext only after all encrypted fields have been assigned.
                credential.secret_reference = None
        migrated += 1

    if apply:
        db.commit()
    else:
        db.rollback()
    remaining = (
        db.query(Credential)
        .filter(
            Credential.encrypted_secret.is_(None)
            if not rewrap
            else or_(
                Credential.encryption_key_id != settings.credential_encryption_active_key_id,
                Credential.encryption_key_id.is_(None),
            )
        )
        .count()
    )
    return migrated, remaining


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy NOVA credentials to AES-256-GCM.")
    parser.add_argument("--apply", action="store_true", help="Write encrypted values and clear legacy plaintext.")
    parser.add_argument("--dry-run", action="store_true", help="Only count rows; this is the default.")
    parser.add_argument("--rewrap", action="store_true", help="Re-encrypt existing ciphertext with the active key.")
    args = parser.parse_args()
    if args.rewrap and not args.apply:
        # Rewrap dry-run is supported; --apply is still required to write.
        pass

    db = SessionLocal()
    try:
        migrated, remaining = migrate(db, apply=args.apply, rewrap=args.rewrap)
        mode = "APPLIED" if args.apply else "DRY-RUN"
        operation = "rewrap" if args.rewrap else "legacy migration"
        print(f"{mode} ({operation}): {'updated' if args.apply else 'would update'}={migrated}; remaining={remaining}")
        if remaining and not args.apply:
            print("Review the count, back up the database, then rerun with --apply.")
        return 0
    except CredentialEncryptionError as exc:
        db.rollback()
        print(f"ERROR: credential encryption is not ready: {exc}")
        return 2
    except Exception:
        db.rollback()
        logger.exception("Credential migration failed.")
        print("ERROR: migration failed; transaction rolled back. Check backend logs.")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
