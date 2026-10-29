import logging
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.auth import get_current_client
from app.database import get_db
from app.email import send_client_self_cancellation_notification
from app.models.admin_user import AdminUser
from app.models.client import Client
from app.models.reservation import Reservation
from app.schemas.client import ClientProfileOut, ClientProfileUpdate
from app.schemas.reservation import ClientReservationOut
from app.utils import normalize_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/client", tags=["Àrea de Client"])


def _get_client_uuid(current_user: dict) -> uuid.UUID:
    sub = current_user.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invàlid")
    try:
        return uuid.UUID(sub)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invàlid")


@router.get("/me", response_model=ClientProfileOut)
async def get_my_profile(
    current_user: dict = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    client_id = _get_client_uuid(current_user)
    client = await db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Perfil no trobat")
    return client


@router.patch("/me", response_model=ClientProfileOut)
async def update_my_profile(
    payload: ClientProfileUpdate,
    current_user: dict = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    client_id = _get_client_uuid(current_user)
    client = await db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Perfil no trobat")

    if payload.email is not None:
        email_norm = normalize_email(str(payload.email))
        if not email_norm:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El correu no pot estar buit")
        if email_norm != client.email:
            dup = await db.execute(
                select(Client).where(func.lower(Client.email) == email_norm, Client.id != client_id)
            )
            if dup.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Aquest correu electrònic ja està en ús.",
                )
            admin_dup = await db.execute(
                select(AdminUser.id).where(func.lower(AdminUser.email) == email_norm)
            )
            if admin_dup.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Aquest correu electrònic ja està en ús.",
                )
        client.email = email_norm

    if payload.name is not None:
        client.name = payload.name.strip()
    if payload.phone is not None:
        client.phone = payload.phone.strip()

    await db.flush()
    await db.refresh(client)
    return client


@router.get("/reservations", response_model=list[ClientReservationOut])
async def list_my_reservations(
    current_user: dict = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Retorna totes les reserves del client autenticat (sense camps de preu ni cobrament)."""
    client_id = _get_client_uuid(current_user)
    res = await db.execute(
        select(Reservation)
        .options(
            joinedload(Reservation.session_type),
            joinedload(Reservation.slot),
            selectinload(Reservation.booked_slots),
        )
        .where(Reservation.client_id == client_id)
        .order_by(Reservation.created_at.desc())
    )
    items = list(res.scalars().unique().all())
    return items


@router.post("/reservations/{reservation_id}/cancel", response_model=ClientReservationOut)
async def cancel_my_reservation(
    reservation_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Cancel·la una reserva futura del client si falten com a mínim 48 hores per a l'inici."""
    client_id = _get_client_uuid(current_user)
    res = await db.execute(
        select(Reservation)
        .options(
            joinedload(Reservation.session_type),
            joinedload(Reservation.slot),
            selectinload(Reservation.booked_slots),
        )
        .where(Reservation.id == reservation_id, Reservation.client_id == client_id)
    )
    reservation = res.scalar_one_or_none()
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reserva no trobada")

    if reservation.status == "cancelled":
        return reservation

    tz = ZoneInfo("Europe/Madrid")
    now_local = datetime.now(tz)

    slots_sorted = (
        sorted(reservation.booked_slots, key=lambda s: s.start_time)
        if reservation.booked_slots
        else ([reservation.slot] if reservation.slot else [])
    )
    first_slot = slots_sorted[0] if slots_sorted else None

    if first_slot is not None:
        slot_dt = datetime.combine(first_slot.date, first_slot.start_time, tzinfo=tz)
        if (slot_dt - now_local) < timedelta(hours=48):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Només es poden cancel·lar sessions des de la web amb un mínim de 48 hores d'antelació. Si us plau, contacta directament amb l'educador.",
            )

    old_slots = list(reservation.booked_slots)
    reservation.status = "cancelled"
    reservation.slot_id = None
    reservation.booked_slots.clear()
    await db.flush()

    from app.routers.reservations import _recalculate_slot_availability
    for s in old_slots:
        await _recalculate_slot_availability(db, s, exclude_reservation_id=reservation.id)

    await db.flush()
    await db.refresh(reservation, attribute_names=["session_type", "slot", "booked_slots"])

    # Avisar a l'educador / administradors per correu
    admins_res = await db.execute(select(AdminUser.email))
    admin_emails = list(admins_res.scalars().all())
    if admin_emails and first_slot is not None:
        background_tasks.add_task(
            send_client_self_cancellation_notification,
            client_name=reservation.client_name,
            client_email=reservation.client_email,
            client_phone=reservation.client_phone,
            session_title=reservation.session_type.name if reservation.session_type else "Sessió",
            date_str=first_slot.date.strftime("%d/%m/%Y"),
            start_time=first_slot.start_time.strftime("%H:%M"),
            admin_emails=admin_emails,
        )

    return reservation
