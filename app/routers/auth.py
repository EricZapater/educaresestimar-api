import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    ADMIN_JWT_EXPIRES_MINUTES,
    CLIENT_JWT_EXPIRES_MINUTES,
    create_access_token,
    generate_reset_token,
    get_current_user,
    get_password_hash,
    hash_reset_token,
    verify_password,
)
from app.database import get_db
from app.email import send_password_reset_email
from app.limiter import limiter
from app.models.admin_user import AdminUser
from app.models.client import Client
from app.models.reservation import Reservation
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)
from app.utils import normalize_email, normalize_phone_digits

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://educaresestimar.cat").rstrip("/")

router = APIRouter(prefix="/api/auth", tags=["Autenticació"])


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verifica credencials (educador o client registrat) i retorna un token JWT amb rol."""
    email_norm = normalize_email(payload.email)
    logger.info("Intent de login per a: %s", email_norm)

    # 1. Comprovar primer si és administrador / educador
    admin_res = await db.execute(
        select(AdminUser).where(func.lower(AdminUser.email) == email_norm)
    )
    admin_user = admin_res.scalar_one_or_none()
    if admin_user and verify_password(payload.password, admin_user.password_hash):
        token_data = {
            "sub": str(admin_user.id),
            "email": admin_user.email,
            "name": admin_user.name,
            "role": "admin",
        }
        token = create_access_token(token_data, expires_minutes=ADMIN_JWT_EXPIRES_MINUTES)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ADMIN_JWT_EXPIRES_MINUTES)
        return TokenResponse(
            token=token,
            role="admin",
            user=UserResponse(
                id=admin_user.id,
                email=admin_user.email,
                name=admin_user.name,
                role="admin",
            ),
            expires_at=expires_at,
        )

    # 2. Comprovar si és un client registrat
    client_res = await db.execute(
        select(Client).where(
            func.lower(Client.email) == email_norm,
            Client.password_hash.is_not(None),
        )
    )
    client_user = client_res.scalar_one_or_none()
    if client_user and client_user.password_hash and verify_password(payload.password, client_user.password_hash):
        token_data = {
            "sub": str(client_user.id),
            "email": client_user.email,
            "name": client_user.name,
            "role": "client",
        }
        token = create_access_token(token_data, expires_minutes=CLIENT_JWT_EXPIRES_MINUTES)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=CLIENT_JWT_EXPIRES_MINUTES)
        return TokenResponse(
            token=token,
            role="client",
            user=UserResponse(
                id=client_user.id,
                email=client_user.email or email_norm or "",
                name=client_user.name,
                phone=client_user.phone,
                role="client",
            ),
            expires_at=expires_at,
        )

    logger.warning("Credencials incorrectes per a %s", email_norm)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Correu o contrasenya incorrectes",
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register_client(
    request: Request,
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Registra un nou compte de client (o activa una fitxa existent vinculant el seu històric)."""
    email_norm = normalize_email(payload.email)
    if not email_norm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El correu és obligatori")

    # No permetre registrar un correu que pertanyi a un admin
    admin_check = await db.execute(
        select(AdminUser.id).where(func.lower(AdminUser.email) == email_norm)
    )
    if admin_check.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Aquest correu electrònic ja té un compte actiu. Inicia sessió.",
        )

    phone_digits = normalize_phone_digits(payload.phone)
    existing_res = await db.execute(
        select(Client).where(func.lower(Client.email) == email_norm)
    )
    client = existing_res.scalar_one_or_none()

    if client is not None and client.password_hash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ja existeix un compte registrat amb aquest correu electrònic.",
        )

    # Si no hi era per email, mirem si tenia fitxa sense email pel mateix telèfon
    if client is None and phone_digits:
        phone_res = await db.execute(
            select(Client).where(
                Client.email.is_(None),
                func.regexp_replace(Client.phone, r"[^0-9]", "", "g") == phone_digits,
            )
        )
        client = phone_res.scalars().first()

    pwd_hash = get_password_hash(payload.password)

    if client is not None:
        client.name = payload.name.strip()
        client.phone = payload.phone.strip()
        client.email = email_norm
        client.password_hash = pwd_hash
    else:
        client = Client(
            name=payload.name.strip(),
            phone=payload.phone.strip(),
            email=email_norm,
            password_hash=pwd_hash,
        )
        db.add(client)

    await db.flush()

    # Vincular qualsevol reserva històrica òrfena amb el mateix email o telèfon
    conds = [func.lower(Reservation.client_email) == email_norm]
    if phone_digits:
        conds.append(func.regexp_replace(Reservation.client_phone, r"[^0-9]", "", "g") == phone_digits)

    orphan_res = await db.execute(
        select(Reservation).where(
            Reservation.client_id.is_(None),
            or_(*conds),
        )
    )
    for r in orphan_res.scalars().all():
        r.client_id = client.id

    await db.flush()
    await db.refresh(client)

    token_data = {
        "sub": str(client.id),
        "email": client.email,
        "name": client.name,
        "role": "client",
    }
    token = create_access_token(token_data, expires_minutes=CLIENT_JWT_EXPIRES_MINUTES)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=CLIENT_JWT_EXPIRES_MINUTES)

    return TokenResponse(
        token=token,
        role="client",
        user=UserResponse(
            id=client.id,
            email=client.email or email_norm,
            name=client.name,
            phone=client.phone,
            role="client",
        ),
        expires_at=expires_at,
    )


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Envia un correu de recuperació si el correu correspon a un client registrat."""
    email_norm = normalize_email(payload.email)
    res = await db.execute(
        select(Client).where(
            func.lower(Client.email) == email_norm,
            Client.password_hash.is_not(None),
        )
    )
    client = res.scalar_one_or_none()
    if client and client.email:
        raw_token, token_hash = generate_reset_token()
        client.reset_token_hash = token_hash
        client.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        await db.flush()
        reset_url = f"{FRONTEND_URL}/restablir-contrasenya?token={raw_token}"
        background_tasks.add_task(
            send_password_reset_email,
            client_name=client.name,
            client_email=client.email,
            reset_url=reset_url,
        )

    return {"message": "Si el correu està registrat, rebràs un enllaç per restablir la contrasenya."}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Restableix la contrasenya d'un client a partir d'un token temporal vàlid."""
    token_hash = hash_reset_token(payload.token.strip())
    now = datetime.now(timezone.utc)

    res = await db.execute(
        select(Client).where(
            Client.reset_token_hash == token_hash,
            Client.reset_token_expires_at.is_not(None),
            Client.reset_token_expires_at > now,
        )
    )
    client = res.scalar_one_or_none()
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="L'enllaç de recuperació no és vàlid o ha caducat.",
        )

    client.password_hash = get_password_hash(payload.new_password)
    client.reset_token_hash = None
    client.reset_token_expires_at = None
    await db.flush()

    return {"message": "Contrasenya actualitzada correctament."}


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
    """Retorna les dades de l'usuari actual (admin o client) segons el seu token."""
    user_id_str = current_user.get("sub")
    role = current_user.get("role", "admin")
    if not user_id_str:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invàlid")

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invàlid")

    if role == "client":
        client = await db.get(Client, user_uuid)
        if not client or not client.password_hash:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client no trobat")
        return UserResponse(
            id=client.id,
            email=client.email or "",
            name=client.name,
            phone=client.phone,
            role="client",
        )

    admin = await db.get(AdminUser, user_uuid)
    if not admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuari no trobat")

    return UserResponse(
        id=admin.id,
        email=admin.email,
        name=admin.name,
        role="admin",
    )
