import logging
import uuid
from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.slot import Slot
from app.models.reservation import Reservation
from app.schemas.slot import SlotCreate, SlotOut, SlotBulkCreate
from app.utils import is_slot_blocked

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/slots", tags=["Slots"])


@router.get("", response_model=list[SlotOut])
async def list_available_slots(
    db: AsyncSession = Depends(get_db),
    from_date: date = Query(..., alias="from", description="Data inici (YYYY-MM-DD)"),
    to_date: date = Query(..., alias="to", description="Data fi (YYYY-MM-DD)"),
):
    """Retorna les franges disponibles dins el rang de dates indicat."""
    logger.info("GET /api/slots from=%s to=%s", from_date, to_date)
    result = await db.execute(
        select(Slot)
        .where(
            and_(
                Slot.date >= from_date,
                Slot.date <= to_date,
                # Slot.is_available == True,
            )
        )
        .order_by(Slot.date, Slot.start_time)
    )
    return result.scalars().all()


@router.post("", response_model=SlotOut, status_code=status.HTTP_201_CREATED)
async def create_slot(
    payload: SlotCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Crea una nova franja horària. Retorna 409 si ja existeix (date+start_time)."""
    logger.info("POST /api/slots date=%s start=%s", payload.date, payload.start_time)

    # Check for existing slot with same date + start_time
    existing = await db.execute(
        select(Slot).where(
            and_(Slot.date == payload.date, Slot.start_time == payload.start_time)
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A slot with this date and start_time already exists",
        )

    slot = Slot(
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
    )
    db.add(slot)
    await db.flush()
    await db.refresh(slot)
    return slot


@router.post("/bulk", response_model=list[SlotOut], status_code=status.HTTP_201_CREATED)
async def create_slots_bulk(
    payload: SlotBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Crea múltiples franges horàries en bloc, ignorant les que ja existeixen o estan bloquejades."""
    logger.info("POST /api/slots/bulk count=%s", len(payload.slots))
    created_slots = []
    for s_payload in payload.slots:
        # Ignorar si està bloquejat
        if is_slot_blocked(s_payload.date, s_payload.start_time):
            continue

        # Check if already exists
        existing = await db.execute(
            select(Slot).where(
                and_(Slot.date == s_payload.date, Slot.start_time == s_payload.start_time)
            )
        )
        existing_slot = existing.scalar_one_or_none()
        if existing_slot is not None:
            # Si ja existeix, assegurem que estigui disponible si no té reserves actives
            from app.models.reservation import reservation_slots
            reservations = await db.execute(
                select(reservation_slots).where(reservation_slots.c.slot_id == existing_slot.id).limit(1)
            )
            if reservations.first() is None:
                existing_slot.is_available = True
                created_slots.append(existing_slot)
            continue

        slot = Slot(
            date=s_payload.date,
            start_time=s_payload.start_time,
            end_time=s_payload.end_time,
            is_available=True,
        )
        db.add(slot)
        created_slots.append(slot)
    
    await db.flush()
    for s in created_slots:
        await db.refresh(s)
    return created_slots



@router.delete("/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_slot(
    slot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Elimina una franja. Retorna 409 si té reserves associades."""
    logger.info("DELETE /api/slots/%s", slot_id)

    slot = await db.get(Slot, slot_id)
    if slot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Slot not found",
        )

    # Check if any reservations reference this slot
    from app.models.reservation import reservation_slots
    reservations = await db.execute(
        select(reservation_slots).where(reservation_slots.c.slot_id == slot_id).limit(1)
    )
    if reservations.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete slot with associated reservations",
        )

    await db.delete(slot)
