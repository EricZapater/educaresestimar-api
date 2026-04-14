import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth import require_api_key
from app.database import get_db
from app.models.reservation import Reservation
from app.models.session_type import SessionType
from app.models.slot import Slot
from app.schemas.reservation import (
    ReservationCreate,
    ReservationCreated,
    ReservationOut,
    ReservationUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reservations", tags=["Reservations"])

VALID_STATUSES = {"pending", "confirmed", "cancelled"}


@router.post("", response_model=ReservationCreated, status_code=status.HTTP_201_CREATED)
async def create_reservation(
    payload: ReservationCreate,
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
    if payload.slot_id is not None:
        slot = await db.get(Slot, payload.slot_id)
        if slot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Slot not found",
            )
        if not slot.is_available:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Slot is not available",
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
    await db.flush()
    await db.refresh(reservation)

    return ReservationCreated(id=reservation.id, status=reservation.status)


@router.get("", response_model=list[ReservationOut])
async def list_reservations(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
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
    _: str = Depends(require_api_key),
):
    """Actualitza status i/o slot_id d'una reserva."""
    logger.info("PATCH /api/reservations/%s", reservation_id)

    reservation = await db.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found",
        )

    if payload.status is not None:
        if payload.status not in VALID_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
            )
        reservation.status = payload.status

    if payload.slot_id is not None:
        slot = await db.get(Slot, payload.slot_id)
        if slot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Slot not found",
            )
        reservation.slot_id = payload.slot_id

    await db.flush()
    await db.refresh(reservation, attribute_names=["session_type", "slot"])

    return reservation
