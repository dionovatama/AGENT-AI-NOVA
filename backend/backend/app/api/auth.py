"""
Authentication endpoints — register & login.

Belum ada di sini (sengaja, sesuai scope Milestone 1):
- RBAC / permission levels
- OpenRouter / AI orchestration
- Tool Manager
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database.models import User
from app.security.hashing import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


# --- Schemas ---

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    is_active: bool

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Endpoints ---

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        # Pesan generik — tidak membedakan "email tidak ditemukan" vs error lain
        # untuk mengurangi enumerasi akun, meski di endpoint register ini
        # transparansi tetap diperlukan.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered.",
        )

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    # Pesan error disamakan untuk "user tidak ada" dan "password salah"
    # agar tidak membocorkan informasi mana yang salah (anti user-enumeration).
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password.",
    )

    if not user or not verify_password(payload.password, user.hashed_password):
        raise invalid_credentials

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )

    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token)
