import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, verify_password, create_access_token, JWT_EXPIRES_MINUTES
from app.database import get_db
from app.limiter import limiter
from app.models.admin_user import AdminUser
from app.schemas.auth import LoginRequest, TokenResponse, UserResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Autenticació"])


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verifica credencials i retorna un token JWT."""
    logger.info("Intento de login para: %s", payload.email)

    result = await db.execute(select(AdminUser).where(AdminUser.email == payload.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.password_hash):
        logger.warning("Credencials incorrectes per a %s", payload.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credencials incorrectes",
        )

    # Creating JWT data payload
    token_data = {"sub": str(user.id), "email": user.email, "name": user.name}
    token = create_access_token(token_data)

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRES_MINUTES)

    return TokenResponse(
        token=token,
        user=UserResponse.model_validate(user),
        expires_at=expires_at,
    )


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(current_user: dict = Depends(get_current_user)):
    """Invalida el token localment. En base JWT stateless, s'esborra al client."""
    logger.info("Logout per l'usuari %s", current_user.get("email"))
    return {"message": "Sessió tancada amb èxit"}


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retorna les dades de l'usuari actual segons el seu token."""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token data")
        
    user = await db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuari no trobat")

    return UserResponse.model_validate(user)
