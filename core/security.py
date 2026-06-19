import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID
from typing import Optional

import bcrypt as bcrypt_lib
from jose import jwt, JWTError
from cryptography.fernet import Fernet
from fastapi import HTTPException, status

from core.config import settings

_fernet = Fernet(settings.ENCRYPTION_KEY.encode())


# ─── Passwords ───────────────────────────────────────────────────────────────
# SHA-256 digest before bcrypt so any-length passwords work.
# bcrypt silently truncates at 72 bytes; pre-hashing avoids that.

def _prepare(password: str) -> bytes:
    return hashlib.sha256(password.encode("utf-8")).digest()  # always 32 bytes


def hash_password(password: str) -> str:
    return bcrypt_lib.hashpw(_prepare(password), bcrypt_lib.gensalt(12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt_lib.checkpw(_prepare(plain), hashed.encode("utf-8"))


# ─── API Key Encryption ───────────────────────────────────────────────────────

def encrypt_secret(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt_secret(encrypted: str) -> str:
    return _fernet.decrypt(encrypted.encode()).decode()


# ─── JWT ─────────────────────────────────────────────────────────────────────

def create_access_token(user_id: UUID, org_id: UUID, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "role": role,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def create_refresh_token(user_id: UUID) -> str:
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalid or expired")


def decode_refresh_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token invalid or expired")
