"""
Password hashing dan JWT helper.

Prinsip keamanan:
- Password plaintext tidak pernah disimpan atau dicatat ke log.
- Hashing menggunakan bcrypt (modern, adaptif, dengan built-in salt).
- JWT secret berasal dari environment, bukan hardcoded.
"""

from datetime import datetime, timedelta, timezone

from jose import jwt, JWTError
from passlib.context import CryptContext

from app.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Hash password menggunakan bcrypt. Tidak pernah mengembalikan/log plaintext."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifikasi password terhadap hash tersimpan."""
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str) -> str:
    """
    Membuat JWT access token.

    subject: identifier user (di NOVA, ini adalah user.id dalam bentuk string).
    Expiration diambil dari config (configurable via environment).
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    """
    Decode dan verifikasi JWT token.
    Mengembalikan subject (user id) jika valid, None jika invalid/expired.
    """
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        return payload.get("sub")
    except JWTError:
        return None
