import logging
import uuid
from datetime import date, datetime, timedelta, time

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from sqlalchemy import select, and_, or_, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models.reservation import Reservation, reservation_slots
from app.models.session_type import SessionType
from app.models.slot import Slot
from app.models.admin_user import AdminUser
from app.email import send_reservation_notification, send_client_confirmation_email
from app.schemas.reservation import (
    ReservationCreate,
    ReservationOut,
    ReservationUpdate,
    ReservationRecurringCreate,
)
from app.utils import is_slot_blocked

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


async def _update_slots_occupancy(
    db: AsyncSession,
    slots: list[Slot],
    session_type: SessionType,
    is_shared: bool,
):
    """Actualitza la disponibilitat dels slots quan són ocupats per una sessió."""
    for s in slots:
        if not is_shared:
            s.is_available = False
        else:
            query = (
                select(func.count(distinct(Reservation.id)))
                .outerjoin(reservation_slots, reservation_slots.c.reservation_id == Reservation.id)
                .where(
                    or_(reservation_slots.c.slot_id == s.id, Reservation.slot_id == s.id),
                    Reservation.status == "confirmed",
                )
            )
            res = await db.execute(query)
            confirmed_count = res.scalar() or 0
            max_clients = session_type.max_clients or 1
            if confirmed_count >= max_clients:
                s.is_available = False
            else:
                s.is_available = True


async def _recalculate_slot_availability(
    db: AsyncSession,
    slot: Slot,
    exclude_reservation_id: uuid.UUID | None = None,
):
    """Recalcula is_available d'un slot quan s'allibera o es cancel·la una reserva."""
    non_shared_conditions = [
        or_(reservation_slots.c.slot_id == slot.id, Reservation.slot_id == slot.id),
        Reservation.status != "cancelled",
        or_(
            Reservation.is_shared == False,
            and_(Reservation.is_shared.is_(None), SessionType.is_shared == False),
        ),
    ]
    if exclude_reservation_id is not None:
        non_shared_conditions.append(Reservation.id != exclude_reservation_id)

    non_shared_query = (
        select(func.count(distinct(Reservation.id)))
        .outerjoin(reservation_slots, reservation_slots.c.reservation_id == Reservation.id)
        .outerjoin(SessionType, SessionType.id == Reservation.session_type_id)
        .where(and_(*non_shared_conditions))
    )
    res_non_shared = await db.execute(non_shared_query)
    non_shared_count = res_non_shared.scalar() or 0
    if non_shared_count > 0:
        slot.is_available = False
        return

    shared_conditions = [
        or_(reservation_slots.c.slot_id == slot.id, Reservation.slot_id == slot.id),
        Reservation.status == "confirmed",
    ]
    if exclude_reservation_id is not None:
        shared_conditions.append(Reservation.id != exclude_reservation_id)

    shared_query = (
        select(
            func.count(distinct(Reservation.id)),
            func.min(SessionType.max_clients),
        )
        .outerjoin(reservation_slots, reservation_slots.c.reservation_id == Reservation.id)
        .outerjoin(SessionType, SessionType.id == Reservation.session_type_id)
        .where(and_(*shared_conditions))
    )
    res_shared = await db.execute(shared_query)
    row = res_shared.first()
    confirmed_count = row[0] if row and row[0] is not None else 0
    min_max_clients = row[1] if row and row[1] is not None else 1
    max_clients = min_max_clients or 1
    slot.is_available = (confirmed_count < max_clients)


@router.post("", response_model=ReservationOut, status_code=status.HTTP_201_CREATED)
async def create_reservation(
    payload: ReservationCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Crea una nova reserva (endpoint públic o manual)."""
    logger.info("POST /api/reservations client=%s", payload.client_name)

    # Validate status if provided
    status_to_use = payload.status or "pending"
    if status_to_use not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

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

    is_shared = payload.is_shared if payload.is_shared is not None else session_type.is_shared

    reservation = Reservation(
        client_name=payload.client_name,
        client_phone=payload.client_phone,
        client_email=payload.client_email,
        session_type_id=payload.session_type_id,
        slot_id=payload.slot_id,
        message=payload.message,
        status=status_to_use,
        is_shared=is_shared,
    )
    
    if slots_to_occupy:
        reservation.booked_slots = slots_to_occupy
        db.add(reservation)
        await db.flush()
        await _update_slots_occupancy(db, slots_to_occupy, session_type, is_shared)
    else:
        db.add(reservation)
        await db.flush()

    await db.refresh(reservation, attribute_names=["session_type", "slot", "booked_slots"])

    # Enviar correu de confirmació al client directament si s'ha creat com a confirmat
    if reservation.status == "confirmed" and reservation.client_email and slots_to_occupy:
        date_str = slots_to_occupy[0].date.strftime("%d/%m/%Y")
        start_time_str = slots_to_occupy[0].start_time.strftime("%H:%M")
        end_time_str = slots_to_occupy[-1].end_time.strftime("%H:%M")
        background_tasks.add_task(
            send_client_confirmation_email,
            client_name=reservation.client_name,
            client_email=reservation.client_email,
            session_title=session_type.name,
            date_str=date_str,
            start_time=start_time_str,
            end_time=end_time_str
        )

    # Obtenir els correus dels administradors
    admins_result = await db.execute(select(AdminUser.email))
    admin_emails = list(admins_result.scalars().all())

    # Només enviar correu de nova reserva a l'admin si és una reserva feta per client (estat pending)
    if admin_emails and reservation.status == "pending":
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


@router.post("/recurring", response_model=list[ReservationOut], status_code=status.HTTP_201_CREATED)
async def create_recurring_reservation(
    payload: ReservationRecurringCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Crea reserves periòdiques (setmanal o quinzenal) per a un client (manual per part de l'educador)."""
    logger.info("POST /api/reservations/recurring client=%s, occurrences=%s", payload.client_name, payload.occurrences)
    
    session_type = await db.get(SessionType, payload.session_type_id)
    if session_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session type not found",
        )
        
    duration = session_type.duration_minutes or 30
    is_shared = payload.is_shared if payload.is_shared is not None else session_type.is_shared
    
    # 1. Calcular les dates de les ocurrències
    dates = []
    curr_date = payload.start_date
    delta_days = 7 if payload.recurrence == "weekly" else 14
    for _ in range(payload.occurrences):
        dates.append(curr_date)
        curr_date += timedelta(days=delta_days)
        
    created_reservations = []
    
    # Helper to get or create a slot
    async def get_or_create_slot(d: date, t: time) -> Slot:
        stmt = select(Slot).where(and_(Slot.date == d, Slot.start_time == t))
        res = await db.execute(stmt)
        slot = res.scalar_one_or_none()
        if not slot:
            # Crear el slot
            minutes = t.hour * 60 + t.minute
            end_minutes = minutes + 30
            end_h, end_m = divmod(end_minutes, 60)
            end_t = time(end_h, end_m)
            
            slot = Slot(date=d, start_time=t, end_time=end_t, is_available=True)
            db.add(slot)
            await db.flush()
        return slot
        
    # 2. Per a cada ocurrència, verificar/crear els slots necessaris
    for occurrence_date in dates:
        slots_needed = []
        curr_mins = payload.start_time.hour * 60 + payload.start_time.minute
        accumulated = 0
        while accumulated < duration:
            h, m = divmod(curr_mins, 60)
            slot_start_t = time(h, m)
            
            slot = await get_or_create_slot(occurrence_date, slot_start_t)
            slots_needed.append(slot)
            
            curr_mins += 30
            accumulated += 30
            
        # Comprovar si algun slot no està disponible
        for s in slots_needed:
            if not s.is_available:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"El slot del dia {occurrence_date.strftime('%d/%m/%Y')} a les {s.start_time.strftime('%H:%M')} ja està reservat o no disponible.",
                )
                
        # Crear la reserva
        reservation = Reservation(
            client_name=payload.client_name,
            client_phone=payload.client_phone,
            client_email=payload.client_email,
            session_type_id=payload.session_type_id,
            slot_id=slots_needed[0].id,
            message=payload.message,
            status="confirmed",
            is_shared=is_shared,
        )
        
        reservation.booked_slots = slots_needed
        db.add(reservation)
        created_reservations.append(reservation)
        
    await db.flush()
    
    for res in created_reservations:
        await _update_slots_occupancy(db, res.booked_slots, session_type, is_shared)

    # 3. Enviar correus de confirmació de cada ocurrència
    for res in created_reservations:
        await db.refresh(res, attribute_names=["session_type", "slot", "booked_slots"])
        if res.client_email and res.booked_slots:
            date_str = res.booked_slots[0].date.strftime("%d/%m/%Y")
            start_time_str = res.booked_slots[0].start_time.strftime("%H:%M")
            end_time_str = res.booked_slots[-1].end_time.strftime("%H:%M")
            
            background_tasks.add_task(
                send_client_confirmation_email,
                client_name=res.client_name,
                client_email=res.client_email,
                session_title=res.session_type.name,
                date_str=date_str,
                start_time=start_time_str,
                end_time=end_time_str
            )
            
    return created_reservations


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
        .options(
            joinedload(Reservation.session_type),
            joinedload(Reservation.slot),
            selectinload(Reservation.booked_slots)
        )
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
    background_tasks: BackgroundTasks,
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

    # Estat previ per decidir si cal notificar al client
    was_already_confirmed = reservation.status == "confirmed"
    original_slot_id = reservation.slot_id
    old_slots = list(reservation.booked_slots)

    # 1. Obtenir slots actualment ocupats per alliberar-los temporalment
    currently_occupying = (reservation.status != "cancelled" and reservation.slot_id is not None)
    if currently_occupying:
        reservation.booked_slots.clear()
        await db.flush()
        for s in old_slots:
            await _recalculate_slot_availability(db, s, exclude_reservation_id=reservation.id)

    # 2. Aplicar els canvis del payload
    if payload.status is not None:
        if payload.status not in VALID_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
            )
        reservation.status = payload.status

    if payload.is_shared is not None:
        reservation.is_shared = payload.is_shared

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
        reservation.booked_slots = new_slots
        await db.flush()

        effective_is_shared = (
            reservation.is_shared
            if reservation.is_shared is not None
            else reservation.session_type.is_shared
        )
        await _update_slots_occupancy(db, new_slots, reservation.session_type, effective_is_shared)

        # Lògica d'enviament de correu al client
        is_now_confirmed = reservation.status == "confirmed"
        status_just_confirmed = is_now_confirmed and not was_already_confirmed
        slot_changed_while_confirmed = is_now_confirmed and was_already_confirmed and reservation.slot_id != original_slot_id
        
        if (status_just_confirmed or slot_changed_while_confirmed) and reservation.client_email and new_slots:
            date_str = new_slots[0].date.strftime("%d/%m/%Y")
            start_time_str = new_slots[0].start_time.strftime("%H:%M")
            end_time_str = new_slots[-1].end_time.strftime("%H:%M")
            
            background_tasks.add_task(
                send_client_confirmation_email,
                client_name=reservation.client_name,
                client_email=reservation.client_email,
                session_title=reservation.session_type.name,
                date_str=date_str,
                start_time=start_time_str,
                end_time=end_time_str
            )

    await db.commit()
    await db.refresh(reservation, attribute_names=["session_type", "slot", "booked_slots"])

    return reservation
