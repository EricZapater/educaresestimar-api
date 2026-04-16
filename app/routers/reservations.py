import logging
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models.reservation import Reservation
from app.models.session_type import SessionType
from app.models.slot import Slot
from app.models.admin_user import AdminUser
from app.email import send_reservation_notification
from app.schemas.reservation import (
    ReservationCreate,
    ReservationOut,
    ReservationUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reservations", tags=["Reservations"])

VALID_STATUSES = {"pending", "confirmed", "cancelled"}


async def _get_slots_to_occupy(db: AsyncSession, start_slot: Slot, session_type: SessionType) -> list[Slot]:
    """Retorna els slots consecutius necessaris per a cobrir la durada de la sessió."""
    duration = session_type.duration_minutes
    if not duration:
        return [start_slot]

    # Obtenir slots d'aquell dia ordenats per hora
    query = (
        select(Slot)
        .where(
            Slot.date == start_slot.date,
            Slot.start_time >= start_slot.start_time
        )
        .order_by(Slot.start_time)
    )
    result = await db.execute(query)
    all_slots = result.scalars().all()

    slots_to_occupy = []
    accumulated_mins = 0
    for s in all_slots:
        slots_to_occupy.append(s)
        dt_start = datetime.combine(s.date, s.start_time)
        dt_end = datetime.combine(s.date, s.end_time)
        accumulated_mins += (dt_end - dt_start).total_seconds() / 60
        if accumulated_mins >= duration:
            break

    if accumulated_mins < duration:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="There are not enough contiguous slots to cover the session duration.",
        )

    return slots_to_occupy


@router.post("", response_model=ReservationOut, status_code=status.HTTP_201_CREATED)
async def create_reservation(
    payload: ReservationCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Crea una nova reserva (endpoint públic)."""
    logger.info("POST /api/reservations client=%s", payload.client_name)

    # Validate session_type_id exists
    session_type = await db.get(SessionType, payload.session_type_id)
    if session_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session type not found",
        )

    # Validate slot_id if provided
    slots_to_occupy = []
    if payload.slot_id is not None:
        slot = await db.get(Slot, payload.slot_id)
        if slot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Slot not found",
            )
            
        slots_to_occupy = await _get_slots_to_occupy(db, slot, session_type)
        if not all(s.is_available for s in slots_to_occupy):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="One or more required slots are not available for the session duration.",
            )

    reservation = Reservation(
        client_name=payload.client_name,
        client_phone=payload.client_phone,
        client_email=payload.client_email,
        session_type_id=payload.session_type_id,
        slot_id=payload.slot_id,
        message=payload.message,
    )
    db.add(reservation)
    
    if slots_to_occupy:
        for s in slots_to_occupy:
            s.is_available = False

    await db.flush()
    await db.refresh(reservation, attribute_names=["session_type", "slot"])

    # Obtenir els correus dels administradors
    admins_result = await db.execute(select(AdminUser.email))
    admin_emails = list(admins_result.scalars().all())

    if admin_emails:
        background_tasks.add_task(
            send_reservation_notification,
            client_name=reservation.client_name,
            client_email=reservation.client_email,
            client_phone=reservation.client_phone,
            message=reservation.message,
            session_title=reservation.session_type.name,
            slot_start=reservation.slot.start_time if reservation.slot else None,
            admin_emails=admin_emails,
        )

    return reservation


@router.get("", response_model=list[ReservationOut])
async def list_reservations(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    from_date: date | None = Query(None, alias="from", description="Data inici (YYYY-MM-DD)"),
    to_date: date | None = Query(None, alias="to", description="Data fi (YYYY-MM-DD)"),
):
    """Llista reserves amb JOIN a session_types i slots. Filtre per dates opcional."""
    logger.info("GET /api/reservations from=%s to=%s", from_date, to_date)

    query = (
        select(Reservation)
        .options(joinedload(Reservation.session_type), joinedload(Reservation.slot))
        .order_by(Reservation.created_at.desc())
    )

    conditions = []
    if from_date is not None:
        conditions.append(Reservation.created_at >= from_date)
    if to_date is not None:
        conditions.append(Reservation.created_at <= to_date)
    if conditions:
        query = query.where(and_(*conditions))

    result = await db.execute(query)
    return result.unique().scalars().all()


@router.patch("/{reservation_id}", response_model=ReservationOut)
async def update_reservation(
    reservation_id: uuid.UUID,
    payload: ReservationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Actualitza status i/o slot_id d'una reserva."""
    logger.info("PATCH /api/reservations/%s", reservation_id)

    reservation = await db.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found",
        )

    # 1. Obtenir slots actualment ocupats per alliberar-los temporalment
    currently_occupying = (reservation.status != "cancelled" and reservation.slot_id is not None)
    if currently_occupying and reservation.slot:
        old_slots = await _get_slots_to_occupy(db, reservation.slot, reservation.session_type)
        for s in old_slots:
            s.is_available = True

    # 2. Aplicar els canvis del payload
    if payload.status is not None:
        if payload.status not in VALID_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
            )
        reservation.status = payload.status

    if payload.slot_id is not None:
        new_slot = await db.get(Slot, payload.slot_id)
        if new_slot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Slot not found",
            )
        reservation.slot_id = payload.slot_id
        # Sobreescrivim la relació temporalment en memòria pel següent càlcul
        reservation.slot = new_slot

    # 3. Tornar a ocupar els nous slots si l'estat final ho requereix
    will_occupy = (reservation.status != "cancelled" and reservation.slot_id is not None)
    if will_occupy and reservation.slot:
        new_slots = await _get_slots_to_occupy(db, reservation.slot, reservation.session_type)
        if not all(s.is_available for s in new_slots):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="One or more required slots are not available for the session duration.",
            )
        for s in new_slots:
            s.is_available = False

    await db.flush()
    await db.refresh(reservation, attribute_names=["session_type", "slot"])

    return reservation
