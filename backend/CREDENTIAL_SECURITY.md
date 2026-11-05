# NOVA Credential Encryption

## Storage contract

New credential writes are encrypted before database persistence with AES-256-GCM.
The legacy request property `secret_reference` remains temporarily for API
compatibility, but it is treated as plaintext input and is **never stored** in
that column. New rows store:

- `encrypted_secret`: base64 AES-GCM ciphertext (the authentication tag is
  appended by the AESGCM implementation).
- `encryption_nonce`: base64 96-bit nonce.
- `encryption_key_id`: keyring identifier.
- `secret_reference`: `NULL` after successful migration.

AES-GCM Additional Authenticated Data binds ciphertext to both `owner_id` and
`credential_id`, preventing ciphertext from being transplanted across tenants
or credential records.

## Key configuration

Generate a 32-byte key:

```bash
python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

Provide it through deployment secret storage / environment variables:

```dotenv
CREDENTIAL_ENCRYPTION_KEYS_JSON={"key-v1":"BASE64_32_BYTE_KEY"}
CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID=key-v1
```

Never commit a real key, put it in the database, or include it in support logs.
The JSON keyring may contain multiple key IDs. Keep old keys available while
records still reference them. Set the active key ID to the key used for new
writes. To rotate, add the new key alongside the old one, switch the active
key ID, then rewrap old rows.

## Database migration and legacy data

1. Take and verify a database backup.
2. Configure the keyring in the backend environment.
3. Apply the schema migration:

   ```bash
   cd backend
   alembic upgrade head
   ```

4. Count legacy rows without changing data:

   ```bash
   python -m app.security.migrate_credentials --dry-run
   ```

5. Encrypt legacy values and clear the old plaintext column:

   ```bash
   python -m app.security.migrate_credentials --apply
   ```

6. Verify the remaining count is zero and verify a known device credential
   can authenticate. Do not delete old database backups until retention policy
   and restore procedures are confirmed.

For key rotation, add the new key to the keyring, change
`CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID`, then run:

```bash
python -m app.security.migrate_credentials --rewrap --dry-run
python -m app.security.migrate_credentials --rewrap --apply
```

Keep the old key until all rows have been rewrapped and a restore test passes.

## Failure behavior

- If encryption keys are missing or invalid, credential creation fails closed
  with HTTP 503.
- If a credential is still legacy/plaintext, execution fails closed and asks
  the operator to run the migration.
- If a key ID is unavailable or AES-GCM authentication fails, NOVA refuses to
  use the credential.
- Decrypted values are only passed into the in-memory execution context. They
  must not be returned by API responses, sent to the LLM, or written to logs.

## Scope

This change encrypts database credentials. It does not yet encrypt configuration
backup files at rest, implement an external KMS integration, or provide hardware
backed key storage. Production deployments should keep the keyring in a managed
secret store and restrict access to the backend process.
