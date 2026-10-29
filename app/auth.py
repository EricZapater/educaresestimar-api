import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key-change-it")
JWT_ALGORITHM = "HS256"
ADMIN_JWT_EXPIRES_MINUTES = 24 * 60  # 24 hours
CLIENT_JWT_EXPIRES_MINUTES = 60 * 24 * 60  # 60 days

# Keep legacy alias for backwards compatibility
JWT_EXPIRES_MINUTES = ADMIN_JWT_EXPIRES_MINUTES

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def generate_reset_token() -> tuple[str, str]:
    """Genera un token segur (raw, sha256_hash) per a restabliment de contrasenya."""
    raw = secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, hashed


def hash_reset_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_access_token(data: dict, expires_minutes: int = ADMIN_JWT_EXPIRES_MINUTES) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    try:
        decoded_token = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return decoded_token
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="La sessió ha caducat",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:  # type: ignore
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invàlid",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Valida qualsevol token JWT vàlid (admin o client)."""
    token = credentials.credentials
    return decode_access_token(token)


async def get_current_admin(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Exigeix un token d'administrador/educador. Els tokens amb role='client' reben 403."""
    user_data = decode_access_token(credentials.credentials)
    # Compatibilitat amb tokens d'admin antics que encara no tenien el camp 'role'
    role = user_data.get("role", "admin")
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accés restringit a l'educador / administrador",
        )
    return user_data


async def get_current_client(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Exigeix un token de client registrat."""
    user_data = decode_access_token(credentials.credentials)
    if user_data.get("role") != "client":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accés exclusiu per a clients registrats",
        )
    return user_data


async def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
) -> dict | None:
    """Retorna les dades del token si se n'ha enviat un de vàlid, o None si és accés públic."""
    if not credentials or not credentials.credentials:
        return None
    try:
        return decode_access_token(credentials.credentials)
    except HTTPException:
        return None
