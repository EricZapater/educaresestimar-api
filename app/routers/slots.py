import logging
import uuid
from datetime import date, time, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_admin, get_optional_current_user
from app.database import get_db
from app.models.slot import Slot
from app.models.reservation import Reservation, reservation_slots
from app.schemas.slot import (
    SlotCreate,
    SlotOut,
    SlotBulkCreate,
    SlotBlockRange,
    SlotUnblockRange,
    SlotReplicateWeek,
)
from app.utils import is_slot_blocked

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/slots", tags=["Slots"])


@router.get("", response_model=list[SlotOut])
async def list_available_slots(
    db: AsyncSession = Depends(get_db),
    current_user: dict | None = Depends(get_optional_current_user),
    from_date: date = Query(..., alias="from", description="Data inici (YYYY-MM-DD)"),
    to_date: date = Query(..., alias="to", description="Data fi (YYYY-MM-DD)"),
    is_shared: bool | None = Query(None, description="Filtra disponibilitat per a tipus de classe compartida o individual"),
):
    """Retorna les franges disponibles dins el rang de dates indicat."""
    logger.info("GET /api/slots from=%s to=%s is_shared=%s", from_date, to_date, is_shared)
    is_admin = bool(current_user and current_user.get("role", "admin") == "admin")

    result = await db.execute(
        select(Slot)
        .where(
            and_(
                Slot.date >= from_date,
                Slot.date <= to_date,
            )
        )
        .order_by(Slot.date, Slot.start_time)
    )
    slots = list(result.scalars().all())

    # Sincronitzar la disponibilitat dinàmica de cada slot segons les reserves multi-client
    from app.routers.reservations import _recalculate_slot_availability
    out: list[SlotOut] = []
    for s in slots:
        info = await _recalculate_slot_availability(db, s)
        slot_is_available = info["is_available"]

        # Si es demana disponibilitat per a una classe individual (is_shared == False),
        # qualsevol slot que ja tingui cap ocupant (encara que sigui compartit) no està disponible
        if is_shared is False and info["current_occupants"] > 0:
            slot_is_available = False

        out.append(
            SlotOut(
                id=s.id,
                date=s.date,
                start_time=s.start_time,
                end_time=s.end_time,
                is_available=slot_is_available,
                is_blocked=bool(s.is_blocked),
                block_reason=s.block_reason if is_admin else None,
                current_occupants=info["current_occupants"],
                is_shared_occupied=info["is_shared_occupied"],
                max_clients=info["max_clients"],
                created_at=s.created_at,
            )
        )
    await db.commit()

    return out


@router.post("", response_model=SlotOut, status_code=status.HTTP_201_CREATED)
async def create_slot(
    payload: SlotCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Crea una nova franja horària. Retorna 409 si ja existeix (date+start_time)."""
    logger.info("POST /api/slots date=%s start=%s", payload.date, payload.start_time)

    existing = await db.execute(
        select(Slot).where(
            and_(Slot.date == payload.date, Slot.start_time == payload.start_time)
        )
    )
    existing_slot = existing.scalar_one_or_none()
    if existing_slot is not None:
        if existing_slot.is_blocked:
            existing_slot.is_blocked = False
            existing_slot.block_reason = None
            existing_slot.is_available = True
            await db.flush()
            await db.refresh(existing_slot)
            return existing_slot
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
    current_user: dict = Depends(get_current_admin),
):
    """Crea múltiples franges horàries en bloc, ignorant les que ja existeixen o estan bloquejades."""
    logger.info("POST /api/slots/bulk count=%s", len(payload.slots))
    created_slots = []
    for s_payload in payload.slots:
        if is_slot_blocked(s_payload.date, s_payload.start_time):
            continue

        existing = await db.execute(
            select(Slot).where(
                and_(Slot.date == s_payload.date, Slot.start_time == s_payload.start_time)
            )
        )
        existing_slot = existing.scalar_one_or_none()
        if existing_slot is not None:
            if existing_slot.is_blocked:
                continue
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


@router.post("/replicate-week", status_code=status.HTTP_201_CREATED)
async def replicate_week_slots(
    payload: SlotReplicateWeek,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Replica l'estructura de franges obertes d'una setmana origen a les properes N setmanes (fins a 12)."""
    week_start = payload.source_week_start - timedelta(days=payload.source_week_start.weekday())
    week_end = week_start + timedelta(days=4)

    logger.info("POST /api/slots/replicate-week source=%s weeks_ahead=%s", week_start, payload.weeks_ahead)

    src_res = await db.execute(
        select(Slot)
        .where(
            Slot.date >= week_start,
            Slot.date <= week_end,
            Slot.is_blocked.is_(False),
        )
        .order_by(Slot.date, Slot.start_time)
    )
    source_slots = list(src_res.scalars().all())
    if not source_slots:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La setmana actual no té cap franja oberta per replicar.",
        )

    created_count = 0
    for w in range(1, payload.weeks_ahead + 1):
        delta = timedelta(days=7 * w)
        for src in source_slots:
            target_date = src.date + delta
            if is_slot_blocked(target_date, src.start_time):
                continue

            existing_res = await db.execute(
                select(Slot).where(
                    and_(Slot.date == target_date, Slot.start_time == src.start_time)
                )
            )
            existing_slot = existing_res.scalar_one_or_none()
            if existing_slot is not None:
                if existing_slot.is_blocked:
                    continue
                res_check = await db.execute(
                    select(reservation_slots)
                    .where(reservation_slots.c.slot_id == existing_slot.id)
                    .limit(1)
                )
                if res_check.first() is None and not existing_slot.is_available:
                    existing_slot.is_available = True
                    created_count += 1
                continue

            new_slot = Slot(
                date=target_date,
                start_time=src.start_time,
                end_time=src.end_time,
                is_available=True,
                is_blocked=False,
            )
            db.add(new_slot)
            created_count += 1

    await db.flush()
    return {
        "created_count": created_count,
        "weeks_ahead": payload.weeks_ahead,
        "source_slots_count": len(source_slots),
    }


@router.post("/block", response_model=list[SlotOut], status_code=status.HTTP_201_CREATED)
async def block_slots_range(
    payload: SlotBlockRange,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Bloqueja un rang d'hores (en trams de 30 min) per a una data amb un motiu personalitzat."""
    logger.info("POST /api/slots/block date=%s %s-%s reason=%s", payload.date, payload.start_time, payload.end_time, payload.reason)

    dt_current = datetime.combine(payload.date, payload.start_time)
    dt_end = datetime.combine(payload.date, payload.end_time)

    if dt_end <= dt_current:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="L'hora de finalització ha de ser posterior a l'hora d'inici.",
        )

    intervals: list[tuple[time, time]] = []
    while dt_current < dt_end:
        next_dt = dt_current + timedelta(minutes=30)
        intervals.append((dt_current.time(), next_dt.time()))
        dt_current = next_dt

    reason_clean = (payload.reason or "").strip() or "No disponible"
    blocked_slots: list[Slot] = []

    for st_time, et_time in intervals:
        existing_res = await db.execute(
            select(Slot).where(
                and_(Slot.date == payload.date, Slot.start_time == st_time)
            )
        )
        existing_slot = existing_res.scalar_one_or_none()

        if existing_slot is not None:
            active_res = await db.execute(
                select(Reservation)
                .outerjoin(reservation_slots, reservation_slots.c.reservation_id == Reservation.id)
                .where(
                    or_(
                        reservation_slots.c.slot_id == existing_slot.id,
                        Reservation.slot_id == existing_slot.id,
                    ),
                    Reservation.status != "cancelled",
                )
                .limit(1)
            )
            if active_res.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"La franja de les {st_time.strftime('%H:%M')} ja té una reserva activa i no es pot bloquejar.",
                )

            existing_slot.is_blocked = True
            existing_slot.is_available = False
            existing_slot.block_reason = reason_clean
            blocked_slots.append(existing_slot)
        else:
            new_slot = Slot(
                date=payload.date,
                start_time=st_time,
                end_time=et_time,
                is_available=False,
                is_blocked=True,
                block_reason=reason_clean,
            )
            db.add(new_slot)
            blocked_slots.append(new_slot)

    await db.flush()
    for s in blocked_slots:
        await db.refresh(s)
    return blocked_slots


@router.post("/unblock", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_slots_range(
    payload: SlotUnblockRange,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Desbloqueja una franja o un rang de franges bloquejades manualment."""
    logger.info("POST /api/slots/unblock date=%s %s-%s", payload.date, payload.start_time, payload.end_time)

    query = select(Slot).where(
        Slot.date == payload.date,
        Slot.is_blocked.is_(True),
    )
    if payload.end_time is not None:
        query = query.where(
            Slot.start_time >= payload.start_time,
            Slot.start_time < payload.end_time,
        )
    else:
        query = query.where(Slot.start_time == payload.start_time)

    result = await db.execute(query)
    slots_to_unblock = list(result.scalars().all())

    for s in slots_to_unblock:
        res_check = await db.execute(
            select(reservation_slots).where(reservation_slots.c.slot_id == s.id).limit(1)
        )
        if res_check.first() is not None:
            s.is_blocked = False
            s.block_reason = None
        else:
            await db.delete(s)


@router.delete("/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_slot(
    slot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Elimina una franja. Retorna 409 si té reserves associades."""
    logger.info("DELETE /api/slots/%s", slot_id)

    slot = await db.get(Slot, slot_id)
    if slot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Slot not found",
        )

    reservations = await db.execute(
        select(reservation_slots).where(reservation_slots.c.slot_id == slot_id).limit(1)
    )
    if reservations.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete slot with associated reservations",
        )

    await db.delete(slot)
