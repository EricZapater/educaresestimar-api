import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_api_key
from app.database import get_db
from app.models.slot import Slot
from app.models.reservation import Reservation
from app.schemas.slot import SlotCreate, SlotOut

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
                Slot.is_available == True,
            )
        )
        .order_by(Slot.date, Slot.start_time)
    )
    return result.scalars().all()


@router.post("", response_model=SlotOut, status_code=status.HTTP_201_CREATED)
async def create_slot(
    payload: SlotCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
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


@router.delete("/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_slot(
    slot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
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
    reservations = await db.execute(
        select(Reservation).where(Reservation.slot_id == slot_id).limit(1)
    )
    if reservations.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete slot with associated reservations",
        )

    await db.delete(slot)
