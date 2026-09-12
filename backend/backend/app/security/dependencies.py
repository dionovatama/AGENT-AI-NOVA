"""
FastAPI dependency untuk mendapatkan user yang sedang login dari JWT.

Endpoint apa pun yang butuh autentikasi (chat, devices, dll di milestone
berikutnya) cukup Depends(get_current_user).
"""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database.models import User
from app.security.hashing import decode_access_token

# HTTPBearer dipakai (bukan OAuth2PasswordBearer) karena /auth/login NOVA
# menerima JSON body {"email", "password"} — bukan form-data OAuth2 standar
# {"username", "password"}. HTTPBearer membuat Swagger UI menampilkan kolom
# sederhana untuk paste token langsung, sesuai alur login custom NOVA.
bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = credentials.credentials
    subject = decode_access_token(token)
    if subject is None:
        raise credentials_error

    try:
        user_id = uuid.UUID(subject)
    except ValueError:
        raise credentials_error

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_error

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )

    return user
