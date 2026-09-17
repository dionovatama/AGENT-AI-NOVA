"""
Sanitization helpers for N.O.V.A — Zero Secret Exposure.

Memastikan password, token, API keys, private keys, dan credential
tidak pernah masuk ke persistent audit logs, database, atau error traces.
"""

from __future__ import annotations

import re
from typing import Any

# Sensitive key patterns (case-insensitive)
_SENSITIVE_KEY_PATTERNS = {
    "password",
    "passwd",
    "secret",
    "token",
    "private_key",
    "api_key",
    "access_token",
    "refresh_token",
    "jwt",
    "authorization",
    "bearer",
    "credential",
    "secret_reference",
}

# Regex to detect JWT strings (header.payload.signature)
_JWT_PATTERN = re.compile(r"^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+$")

# Regex to detect database credentials in URLs: scheme://user:pass@host
_DB_URL_PATTERN = re.compile(r"://([^:]+):([^@]+)@")


def _is_sensitive_key(key: str) -> bool:
    """Memeriksa apakah nama key berpotensi menyimpan credential/secret."""
    key_lower = key.lower().replace("-", "_")
    return any(pattern in key_lower for pattern in _SENSITIVE_KEY_PATTERNS)


def _sanitize_string_value(val: str) -> str:
    """Redact string jika terindikasi sebagai JWT atau private key PEM."""
    if "BEGIN" in val and "PRIVATE KEY" in val:
        return "[REDACTED_PRIVATE_KEY]"

    if len(val) > 20 and val.startswith("eyJ") and _JWT_PATTERN.match(val):
        return "[REDACTED_JWT]"

    # Sanitasi database URL jika ada password di dalamnya
    if "://" in val and "@" in val:
        return _DB_URL_PATTERN.sub(r"://\1:[REDACTED]@\2", val)

    return val


def sanitize_metadata(data: Any) -> Any:
    """
    Menyaring data struktur (dict, list, atau nilai skalar) secara rekursif.
    Semua key/value sensitif diganti dengan '[REDACTED]'.
    """
    if isinstance(data, dict):
        sanitized: dict[str, Any] = {}
        for k, v in data.items():
            if _is_sensitive_key(str(k)):
                sanitized[str(k)] = "[REDACTED]"
            else:
                sanitized[str(k)] = sanitize_metadata(v)
        return sanitized

    if isinstance(data, (list, tuple, set)):
        return [sanitize_metadata(item) for item in data]

    if isinstance(data, str):
        return _sanitize_string_value(data)

    return data


def sanitize_error_message(error: str | None) -> str | None:
    """
    Membersihkan pesan error dari kemungkinan bocoran database password,
    token, atau credential sebelum dikembalikan ke caller atau disimpan ke log.
    """
    if error is None:
        return None

    sanitized = str(error)

    # Redact database URLs with passwords
    sanitized = _DB_URL_PATTERN.sub(r"://\1:[REDACTED]@", sanitized)

    # Redact private keys if present
    if "BEGIN" in sanitized and "PRIVATE KEY" in sanitized:
        sanitized = re.sub(
            r"-----BEGIN [A-Z ]+PRIVATE KEY-----[^-]+-----END [A-Z ]+PRIVATE KEY-----",
            "[REDACTED_PRIVATE_KEY]",
            sanitized,
            flags=re.DOTALL,
        )

    # Redact potential JWTs in error strings
    sanitized = re.sub(
        r"eyJ[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+",
        "[REDACTED_JWT]",
        sanitized,
    )

    return sanitized
