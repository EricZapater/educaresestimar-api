import uuid
from datetime import date, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client, ClientSessionPrice
from app.models.session_type import SessionType


def is_slot_blocked(d: date, t: time) -> bool:
    """
    Comprova si una franja horària està bloquejada:
    - Dilluns, dimarts i divendres matins bloquejats (inici abans de les 12:00h).
    - Dimarts tarda bloquejat (inici a partir de les 15:00h).
    """
    # weekday(): 0=Dilluns, 1=Dimarts, 4=Divendres
    wd = d.weekday()

    # Dilluns, dimarts i divendres matins (< 12:00)
    if wd in (0, 1, 4) and t < time(12, 0):
        return True

    # Dimarts tarda (>= 15:00)
    if wd == 1 and t >= time(15, 0):
        return True

    return False


def normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    cleaned = email.strip().lower()
    return cleaned if cleaned else None


def normalize_phone_digits(phone: str | None) -> str:
    if not phone:
        return ""
    return "".join(ch for ch in phone if ch.isdigit())


async def find_or_create_client(
    db: AsyncSession,
    name: str,
    phone: str,
    email: str | None = None,
    authenticated_client_id: uuid.UUID | None = None,
) -> Client:
    """Troba un client existent per ID autenticat, email o telèfon, o en crea la fitxa interna."""
    if authenticated_client_id is not None:
        existing_auth = await db.get(Client, authenticated_client_id)
        if existing_auth is not None:
            return existing_auth

    email_norm = normalize_email(email)
    phone_digits = normalize_phone_digits(phone)

    if email_norm:
        res = await db.execute(select(Client).where(func.lower(Client.email) == email_norm))
        found = res.scalar_one_or_none()
        if found is not None:
            return found

    if phone_digits:
        res = await db.execute(
            select(Client).where(
                func.regexp_replace(Client.phone, r"[^0-9]", "", "g") == phone_digits
            )
        )
        found = res.scalars().first()
        if found is not None:
            if email_norm and not found.email:
                found.email = email_norm
            return found

    new_client = Client(
        name=name.strip() or "Client",
        phone=phone.strip(),
        email=email_norm,
    )
    db.add(new_client)
    await db.flush()
    return new_client


async def resolve_session_price(
    db: AsyncSession,
    client_id: uuid.UUID | None,
    session_type: SessionType,
    explicit_admin_price: float | None = None,
) -> Decimal:
    """Calcula el preu segons la cascada: 1) explícit admin, 2) tarifa client, 3) preu base classe."""
    if explicit_admin_price is not None:
        return Decimal(str(round(explicit_admin_price, 2)))

    if client_id is not None:
        res = await db.execute(
            select(ClientSessionPrice).where(
                ClientSessionPrice.client_id == client_id,
                ClientSessionPrice.session_type_id == session_type.id,
            )
        )
        custom = res.scalar_one_or_none()
        if custom is not None:
            return custom.price

    return session_type.default_price if session_type.default_price is not None else Decimal("0.00")
