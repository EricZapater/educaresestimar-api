import logging
import uuid
from datetime import date, datetime, timedelta, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.auth import get_current_admin, get_current_client, get_optional_current_user
from app.database import get_db
from app.models.client import Client
from app.models.reservation import Reservation, reservation_slots
from app.models.session_type import SessionType
from app.models.slot import Slot
from app.models.admin_user import AdminUser
from app.email import (
    send_reservation_notification,
    send_client_confirmation_email,
    send_client_cancellation_email,
    send_series_admin_notification,
    send_series_client_status_email,
)
from app.schemas.reservation import (
    ClientReservationOut,
    RecurringCheckRequest,
    RecurringCheckResponse,
    RecurringClientSubmitRequest,
    RecurringOccurrenceCheckOut,
    ReservationCreate,
    ReservationOut,
    ReservationUpdate,
    ReservationRecurringCreate,
)
from app.schemas.slot import SlotOut
from app.utils import find_or_create_client, resolve_session_price

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

    slots_to_occupy: list[Slot] = []
    accumulated_mins = 0.0
    prev_end: time | None = None
    for s in all_slots:
        if prev_end is not None and s.start_time != prev_end:
            break
        slots_to_occupy.append(s)
        prev_end = s.end_time
        dt_start = datetime.combine(s.date, s.start_time)
        dt_end = datetime.combine(s.date, s.end_time)
        accumulated_mins += (dt_end - dt_start).total_seconds() / 60
        if accumulated_mins >= duration:
            break

    if accumulated_mins < duration:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No hi ha prou franges consecutives disponibles per cobrir la durada de la sessió.",
        )

    return slots_to_occupy


async def _recalculate_slot_availability(
    db: AsyncSession,
    slot: Slot,
    exclude_reservation_id: uuid.UUID | None = None,
) -> dict:
    """
    Recalcula is_available d'un slot en funció de les reserves actives que l'ocupen.
    Retorna un diccionari amb les dades d'ocupació:
    {
        "is_available": bool,
        "current_occupants": int,
        "is_shared_occupied": bool,
        "max_clients": int | None,
    }
    """
    query = (
        select(Reservation, SessionType)
        .join(SessionType, SessionType.id == Reservation.session_type_id)
        .outerjoin(
            reservation_slots,
            and_(
                reservation_slots.c.reservation_id == Reservation.id,
                reservation_slots.c.slot_id == slot.id,
            ),
        )
        .where(
            or_(reservation_slots.c.slot_id == slot.id, Reservation.slot_id == slot.id),
            Reservation.status != "cancelled",
        )
        .distinct()
    )
    if exclude_reservation_id is not None:
        query = query.where(Reservation.id != exclude_reservation_id)

    res = await db.execute(query)
    rows = res.all()

    # Deduplicar reserves per ID per evitar recomptes múltiples per slots consecutius
    unique_reservations = {}
    for r, st in rows:
        unique_reservations[r.id] = (r, st)

    # Si el slot està bloquejat per l'educador amb un motiu, mai està disponible
    if slot.is_blocked:
        slot.is_available = False
        return {
            "is_available": False,
            "current_occupants": len(unique_reservations),
            "is_shared_occupied": False,
            "max_clients": None,
        }

    if not unique_reservations:
        slot.is_available = True
        return {
            "is_available": True,
            "current_occupants": 0,
            "is_shared_occupied": False,
            "max_clients": None,
        }

    has_non_shared = False
    max_clients_candidates = []

    for r, st in unique_reservations.values():
        is_r_shared = bool(r.is_shared or st.is_shared)
        if not is_r_shared:
            has_non_shared = True
            break
        limit = st.max_clients if (st.max_clients and st.max_clients > 1) else (2 if r.is_shared else 1)
        max_clients_candidates.append(limit)

    current_occupants = len(unique_reservations)

    if has_non_shared:
        slot.is_available = False
        return {
            "is_available": False,
            "current_occupants": current_occupants,
            "is_shared_occupied": False,
            "max_clients": None,
        }

    # Totes són compartides
    max_clients = min(max_clients_candidates) if max_clients_candidates else 1
    slot.is_available = (current_occupants < max_clients)
    return {
        "is_available": slot.is_available,
        "current_occupants": current_occupants,
        "is_shared_occupied": True,
        "max_clients": max_clients,
    }


async def _update_slots_occupancy(
    db: AsyncSession,
    slots: list[Slot],
    session_type: SessionType,
    is_shared: bool,
):
    """Actualitza la disponibilitat dels slots quan són ocupats per una sessió."""
    for s in slots:
        await _recalculate_slot_availability(db, s)


def _public_slot_out(slot: Slot, occ_info: dict | None = None) -> SlotOut:
    """Construeix un SlotOut per a clients sense exposar mai block_reason."""
    return SlotOut(
        id=slot.id,
        date=slot.date,
        start_time=slot.start_time,
        end_time=slot.end_time,
        is_available=occ_info["is_available"] if occ_info is not None else slot.is_available,
        is_blocked=slot.is_blocked,
        block_reason=None,
        current_occupants=occ_info["current_occupants"] if occ_info is not None else 0,
        is_shared_occupied=occ_info["is_shared_occupied"] if occ_info is not None else False,
        max_clients=occ_info["max_clients"] if occ_info is not None else None,
        created_at=slot.created_at,
    )


def _format_reservation_slot_label(res: Reservation) -> str:
    slots_sorted = (
        sorted(res.booked_slots, key=lambda s: s.start_time)
        if res.booked_slots
        else ([res.slot] if res.slot else [])
    )
    if not slots_sorted:
        return "Pendent d'horari"
    first_s = slots_sorted[0]
    last_s = slots_sorted[-1]
    return f"{first_s.date.strftime('%d/%m/%Y')} ({first_s.start_time.strftime('%H:%M')} - {last_s.end_time.strftime('%H:%M')})"


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
async def create_reservation(
    payload: ReservationCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict | None = Depends(get_optional_current_user),
):
    """Crea una nova reserva (pública, client registrat o manual d'administrador)."""
    logger.info("POST /api/reservations client=%s", payload.client_name)

    is_admin = bool(current_user and current_user.get("role", "admin") == "admin")
    auth_client_id: uuid.UUID | None = None
    if current_user and current_user.get("role") == "client" and current_user.get("sub"):
        try:
            auth_client_id = uuid.UUID(current_user["sub"])
        except ValueError:
            auth_client_id = None

    # Només l'educador/admin pot crear directament en estat confirmat o forçar preu
    status_to_use = (payload.status or "pending") if is_admin else "pending"
    if status_to_use not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

    session_type = await db.get(SessionType, payload.session_type_id)
    if session_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session type not found",
        )

    is_shared = (
        payload.is_shared
        if (is_admin and payload.is_shared is not None)
        else session_type.is_shared
    )

    slots_to_occupy: list[Slot] = []
    if payload.slot_id is not None:
        slot = await db.get(Slot, payload.slot_id)
        if slot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Slot not found",
            )

        slots_to_occupy = await _get_slots_to_occupy(db, slot, session_type)
        if not all((s.is_available and not s.is_blocked) for s in slots_to_occupy):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Una o més franges necessàries per a la durada de la sessió no estan disponibles.",
            )

        if not is_shared:
            for s in slots_to_occupy:
                info = await _recalculate_slot_availability(db, s)
                if info["current_occupants"] > 0:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Aquest horari té una classe compartida activa i no admet sessions individuals.",
                    )

    # Vincular o crear fitxa de client i resoldre preu segons cascada de tarifes
    client = await find_or_create_client(
        db,
        name=payload.client_name,
        phone=payload.client_phone,
        email=payload.client_email,
        authenticated_client_id=auth_client_id,
    )
    resolved_price = await resolve_session_price(
        db,
        client_id=client.id,
        session_type=session_type,
        explicit_admin_price=payload.price if is_admin else None,
    )

    reservation = Reservation(
        client_id=client.id,
        client_name=payload.client_name.strip(),
        client_phone=payload.client_phone.strip(),
        client_email=payload.client_email.strip() if payload.client_email else client.email,
        session_type_id=payload.session_type_id,
        slot_id=payload.slot_id,
        message=payload.message,
        status=status_to_use,
        is_shared=is_shared,
        price=resolved_price,
        amount_paid=Decimal("0.00"),
    )

    if slots_to_occupy:
        reservation.booked_slots = slots_to_occupy
        db.add(reservation)
        await db.flush()
        await _update_slots_occupancy(db, slots_to_occupy, session_type, is_shared)
    else:
        db.add(reservation)
        await db.flush()

    await db.commit()
    await db.refresh(reservation, attribute_names=["session_type", "slot", "booked_slots"])

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
            end_time=end_time_str,
        )

    admins_result = await db.execute(select(AdminUser.email))
    admin_emails = list(admins_result.scalars().all())

    if admin_emails and reservation.status == "pending":
        slot_dt = (
            datetime.combine(reservation.slot.date, reservation.slot.start_time)
            if reservation.slot
            else None
        )
        background_tasks.add_task(
            send_reservation_notification,
            client_name=reservation.client_name,
            client_email=reservation.client_email or "-",
            client_phone=reservation.client_phone,
            message=reservation.message,
            session_title=reservation.session_type.name,
            slot_start=slot_dt,
            admin_emails=admin_emails,
        )

    if is_admin:
        return ReservationOut.model_validate(reservation).model_dump(mode="json", by_alias=True)

    # Sanititzar block_reason i camps econòmics per a clients i visitants públics
    out = ClientReservationOut.model_validate(reservation)
    if out.slot:
        out.slot.block_reason = None
    for bs in out.booked_slots:
        bs.block_reason = None
    return out.model_dump(mode="json", by_alias=True)


@router.post("/recurring", response_model=list[ReservationOut], status_code=status.HTTP_201_CREATED)
async def create_recurring_reservation(
    payload: ReservationRecurringCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
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

    client = await find_or_create_client(
        db,
        name=payload.client_name,
        phone=payload.client_phone,
        email=payload.client_email,
    )
    resolved_price = await resolve_session_price(db, client.id, session_type)
    group_id = uuid.uuid4() if payload.occurrences > 1 else None

    dates = []
    curr_date = payload.start_date
    delta_days = 7 if payload.recurrence == "weekly" else 14
    for _ in range(payload.occurrences):
        dates.append(curr_date)
        curr_date += timedelta(days=delta_days)

    created_reservations: list[Reservation] = []

    async def get_or_create_slot(d: date, t: time) -> Slot:
        stmt = select(Slot).where(and_(Slot.date == d, Slot.start_time == t))
        res = await db.execute(stmt)
        slot = res.scalar_one_or_none()
        if not slot:
            minutes = t.hour * 60 + t.minute
            end_minutes = minutes + 30
            end_h, end_m = divmod(end_minutes, 60)
            end_t = time(end_h, end_m)

            slot = Slot(date=d, start_time=t, end_time=end_t, is_available=True)
            db.add(slot)
            await db.flush()
        return slot

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

        for s in slots_needed:
            if not s.is_available or s.is_blocked:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"El slot del dia {occurrence_date.strftime('%d/%m/%Y')} a les {s.start_time.strftime('%H:%M')} ja està reservat o no disponible.",
                )
            if not is_shared:
                info = await _recalculate_slot_availability(db, s)
                if info["current_occupants"] > 0:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"El slot del dia {occurrence_date.strftime('%d/%m/%Y')} a les {s.start_time.strftime('%H:%M')} té una sessió compartida activa.",
                    )

        reservation = Reservation(
            client_id=client.id,
            recurrence_group_id=group_id,
            client_name=payload.client_name.strip(),
            client_phone=payload.client_phone.strip(),
            client_email=payload.client_email.strip() if payload.client_email else client.email,
            session_type_id=payload.session_type_id,
            slot_id=slots_needed[0].id,
            message=payload.message,
            status="confirmed",
            is_shared=is_shared,
            price=resolved_price,
            amount_paid=Decimal("0.00"),
        )

        reservation.booked_slots = slots_needed
        db.add(reservation)
        created_reservations.append(reservation)

    await db.flush()

    for res in created_reservations:
        await _update_slots_occupancy(db, res.booked_slots, session_type, is_shared)

    await db.commit()
    for res in created_reservations:
        await db.refresh(res, attribute_names=["session_type", "slot", "booked_slots"])

    # Enviar 1 sol correu resum si és una sèrie, o confirmació individual si és 1 sola sessió
    recipient_email = created_reservations[0].client_email if created_reservations else None
    if recipient_email and created_reservations:
        if len(created_reservations) > 1:
            dates_list = [_format_reservation_slot_label(r) for r in created_reservations]
            background_tasks.add_task(
                send_series_client_status_email,
                client_name=created_reservations[0].client_name,
                client_email=recipient_email,
                session_title=session_type.name,
                dates_list=dates_list,
                approved=True,
            )
        elif created_reservations[0].booked_slots:
            first_res = created_reservations[0]
            background_tasks.add_task(
                send_client_confirmation_email,
                client_name=first_res.client_name,
                client_email=recipient_email,
                session_title=session_type.name,
                date_str=first_res.booked_slots[0].date.strftime("%d/%m/%Y"),
                start_time=first_res.booked_slots[0].start_time.strftime("%H:%M"),
                end_time=first_res.booked_slots[-1].end_time.strftime("%H:%M"),
            )

    return created_reservations


@router.post("/recurring-check", response_model=RecurringCheckResponse)
async def check_client_recurring_series(
    payload: RecurringCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_client),
):
    """Comprova la disponibilitat d'una sèrie periòdica per a un client registrat (màx. 3 mesos) i proposa alternatives per als dies amb conflicte."""
    if payload.recurrence not in ("weekly", "biweekly"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La periodicitat ha de ser 'weekly' o 'biweekly'.",
        )

    session_type = await db.get(SessionType, payload.session_type_id)
    if session_type is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tipus de sessió no trobat")

    start_slot = await db.get(Slot, payload.start_slot_id)
    if start_slot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Franja inicial no trobada")

    duration = session_type.duration_minutes or 30
    is_shared = bool(session_type.is_shared)
    delta_days = 7 if payload.recurrence == "weekly" else 14
    max_end_date = start_slot.date + timedelta(days=92)  # Màxim 3 mesos des de l'inici

    target_dates: list[date] = []
    curr_d = start_slot.date
    for _ in range(payload.occurrences):
        if curr_d > max_end_date:
            break
        target_dates.append(curr_d)
        curr_d += timedelta(days=delta_days)

    if not target_dates:
        return RecurringCheckResponse(occurrences=[], has_conflicts=False)

    # Carregar totes les franges de les setmanes afectades d'un sol cop
    first_monday = target_dates[0] - timedelta(days=target_dates[0].weekday())
    last_friday = (target_dates[-1] - timedelta(days=target_dates[-1].weekday())) + timedelta(days=4)

    slots_res = await db.execute(
        select(Slot)
        .where(Slot.date >= first_monday, Slot.date <= last_friday)
        .order_by(Slot.date, Slot.start_time)
    )
    all_slots = list(slots_res.scalars().all())

    occupancy_map: dict[uuid.UUID, dict] = {}
    slots_by_date: dict[date, list[Slot]] = {}
    for s in all_slots:
        occ = await _recalculate_slot_availability(db, s)
        occupancy_map[s.id] = occ
        slots_by_date.setdefault(s.date, []).append(s)

    now_madrid = datetime.now(ZoneInfo("Europe/Madrid"))

    def can_start_at(day_slots: list[Slot], idx: int) -> Slot | None:
        first_s = day_slots[idx]
        # Evitar oferir franges ja passades
        if datetime.combine(first_s.date, first_s.start_time, tzinfo=ZoneInfo("Europe/Madrid")) <= now_madrid:
            return None

        acc = 0.0
        prev_end: time | None = None
        for s in day_slots[idx:]:
            if prev_end is not None and s.start_time != prev_end:
                return None
            occ = occupancy_map[s.id]
            if s.is_blocked or not occ["is_available"]:
                return None
            if not is_shared and occ["current_occupants"] > 0:
                return None
            prev_end = s.end_time
            dt_s = datetime.combine(s.date, s.start_time)
            dt_e = datetime.combine(s.date, s.end_time)
            acc += (dt_e - dt_s).total_seconds() / 60
            if acc >= duration:
                return first_s
        return None

    occurrences_out: list[RecurringOccurrenceCheckOut] = []
    has_conflicts = False

    for idx, occ_date in enumerate(target_dates):
        day_slots = slots_by_date.get(occ_date, [])
        matched_slot: Slot | None = None
        for i, s in enumerate(day_slots):
            if s.start_time == start_slot.start_time:
                matched_slot = can_start_at(day_slots, i)
                break

        if matched_slot is not None:
            occurrences_out.append(
                RecurringOccurrenceCheckOut(
                    occurrence_index=idx + 1,
                    target_date=occ_date,
                    target_time=start_slot.start_time,
                    status="available",
                    slot=_public_slot_out(matched_slot, occupancy_map[matched_slot.id]),
                    alternative_slots=[],
                )
            )
        else:
            has_conflicts = True
            week_monday = occ_date - timedelta(days=occ_date.weekday())
            week_has_any_slots = False
            alternatives: list[SlotOut] = []

            for offset in range(5):  # Dilluns a Divendres d'aquella mateixa setmana
                wd_date = week_monday + timedelta(days=offset)
                wd_slots = slots_by_date.get(wd_date, [])
                if wd_slots:
                    week_has_any_slots = True
                for i in range(len(wd_slots)):
                    valid_start = can_start_at(wd_slots, i)
                    if valid_start is not None:
                        alternatives.append(_public_slot_out(valid_start, occupancy_map[valid_start.id]))

            reason = (
                "Franja ocupada o sense prou temps seguit disponible"
                if week_has_any_slots
                else "Setmana encara no oberta per l'educador"
            )
            occurrences_out.append(
                RecurringOccurrenceCheckOut(
                    occurrence_index=idx + 1,
                    target_date=occ_date,
                    target_time=start_slot.start_time,
                    status="conflict",
                    reason=reason,
                    slot=None,
                    alternative_slots=alternatives,
                )
            )

    return RecurringCheckResponse(occurrences=occurrences_out, has_conflicts=has_conflicts)


@router.post("/recurring-submit", response_model=list[ClientReservationOut], status_code=status.HTTP_201_CREATED)
async def submit_client_recurring_series(
    payload: RecurringClientSubmitRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_client),
):
    """Registra una sèrie de reserves en estat 'pending' per a un client registrat i envia 1 sol avís resum a l'educador."""
    try:
        client_id = uuid.UUID(current_user["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invàlid")

    client = await db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client no trobat")

    session_type = await db.get(SessionType, payload.session_type_id)
    if session_type is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tipus de sessió no trobat")

    # Deduplicar mantenint l'ordre
    unique_slot_ids: list[uuid.UUID] = []
    for sid in payload.slot_ids:
        if sid not in unique_slot_ids:
            unique_slot_ids.append(sid)

    if not unique_slot_ids or len(unique_slot_ids) > 13:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de sessions de la sèrie ha d'estar entre 1 i 13.",
        )

    start_slots: list[Slot] = []
    for sid in unique_slot_ids:
        s = await db.get(Slot, sid)
        if s is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Una de les franges seleccionades no existeix.")
        start_slots.append(s)

    start_slots.sort(key=lambda s: (s.date, s.start_time))

    # Evitar dues sessions el mateix dia dins d'una mateixa sèrie o horitzó > 3 mesos
    if (start_slots[-1].date - start_slots[0].date).days > 95:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Les reserves periòdiques tenen un màxim de 3 mesos de durada.",
        )

    is_shared = bool(session_type.is_shared)
    resolved_price = await resolve_session_price(db, client.id, session_type)
    group_id = uuid.uuid4() if len(start_slots) > 1 else None

    created_reservations: list[Reservation] = []

    for start_s in start_slots:
        slots_to_occupy = await _get_slots_to_occupy(db, start_s, session_type)
        if not all((s.is_available and not s.is_blocked) for s in slots_to_occupy):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La franja del dia {start_s.date.strftime('%d/%m/%Y')} a les {start_s.start_time.strftime('%H:%M')} ja no està disponible.",
            )
        if not is_shared:
            for s in slots_to_occupy:
                info = await _recalculate_slot_availability(db, s)
                if info["current_occupants"] > 0:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"La franja del dia {start_s.date.strftime('%d/%m/%Y')} a les {start_s.start_time.strftime('%H:%M')} té una classe compartida activa.",
                    )

        reservation = Reservation(
            client_id=client.id,
            recurrence_group_id=group_id,
            client_name=client.name,
            client_phone=client.phone,
            client_email=client.email,
            session_type_id=session_type.id,
            slot_id=start_s.id,
            message=payload.message,
            status="pending",
            is_shared=is_shared,
            price=resolved_price,
            amount_paid=Decimal("0.00"),
        )
        reservation.booked_slots = slots_to_occupy
        db.add(reservation)
        await db.flush()
        await _update_slots_occupancy(db, slots_to_occupy, session_type, is_shared)
        created_reservations.append(reservation)

    await db.commit()
    for r in created_reservations:
        await db.refresh(r, attribute_names=["session_type", "slot", "booked_slots"])

    admins_result = await db.execute(select(AdminUser.email))
    admin_emails = list(admins_result.scalars().all())
    if admin_emails:
        if len(created_reservations) > 1:
            dates_list = [_format_reservation_slot_label(r) for r in created_reservations]
            background_tasks.add_task(
                send_series_admin_notification,
                client_name=client.name,
                client_email=client.email,
                client_phone=client.phone,
                message=payload.message,
                session_title=session_type.name,
                dates_list=dates_list,
                admin_emails=admin_emails,
            )
        else:
            first_r = created_reservations[0]
            slot_dt = (
                datetime.combine(first_r.slot.date, first_r.slot.start_time)
                if first_r.slot
                else None
            )
            background_tasks.add_task(
                send_reservation_notification,
                client_name=client.name,
                client_email=client.email or "-",
                client_phone=client.phone,
                message=payload.message,
                session_title=session_type.name,
                slot_start=slot_dt,
                admin_emails=admin_emails,
            )

    out_list: list[ClientReservationOut] = []
    for r in created_reservations:
        item = ClientReservationOut.model_validate(r)
        if item.slot:
            item.slot.block_reason = None
        for bs in item.booked_slots:
            bs.block_reason = None
        out_list.append(item)
    return out_list


@router.post("/series/{group_id}/approve", response_model=list[ReservationOut])
async def approve_reservation_series(
    group_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Aprova de cop totes les reserves pendents d'una sèrie periòdica i envia 1 sol correu resum al client."""
    res = await db.execute(
        select(Reservation)
        .options(
            joinedload(Reservation.session_type),
            joinedload(Reservation.slot),
            selectinload(Reservation.booked_slots),
        )
        .where(Reservation.recurrence_group_id == group_id, Reservation.status == "pending")
    )
    pending_items = list(res.scalars().unique().all())
    if not pending_items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hi ha reserves pendents per aprovar en aquesta sèrie.",
        )

    pending_items.sort(key=lambda r: (r.slot.date if r.slot else date.max, r.slot.start_time if r.slot else time.min))

    for r in pending_items:
        r.status = "confirmed"

    await db.flush()
    for r in pending_items:
        if r.booked_slots and r.session_type:
            await _update_slots_occupancy(db, r.booked_slots, r.session_type, bool(r.is_shared or r.session_type.is_shared))

    await db.commit()
    for r in pending_items:
        await db.refresh(r, attribute_names=["session_type", "slot", "booked_slots"])

    first_r = pending_items[0]
    if first_r.client_email:
        dates_list = [_format_reservation_slot_label(r) for r in pending_items]
        background_tasks.add_task(
            send_series_client_status_email,
            client_name=first_r.client_name,
            client_email=first_r.client_email,
            session_title=first_r.session_type.name if first_r.session_type else "Sessió",
            dates_list=dates_list,
            approved=True,
        )

    return pending_items


@router.post("/series/{group_id}/reject", response_model=list[ReservationOut])
async def reject_reservation_series(
    group_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Rebutja totes les reserves pendents d'una sèrie periòdica, n'allibera les franges i envia 1 sol correu resum."""
    res = await db.execute(
        select(Reservation)
        .options(
            joinedload(Reservation.session_type),
            joinedload(Reservation.slot),
            selectinload(Reservation.booked_slots),
        )
        .where(Reservation.recurrence_group_id == group_id, Reservation.status == "pending")
    )
    pending_items = list(res.scalars().unique().all())
    if not pending_items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hi ha reserves pendents per rebutjar en aquesta sèrie.",
        )

    pending_items.sort(key=lambda r: (r.slot.date if r.slot else date.max, r.slot.start_time if r.slot else time.min))
    dates_list = [_format_reservation_slot_label(r) for r in pending_items]
    first_r = pending_items[0]
    client_email = first_r.client_email
    client_name = first_r.client_name
    session_title = first_r.session_type.name if first_r.session_type else "Sessió"

    slots_to_recalc: list[Slot] = []
    for r in pending_items:
        slots_to_recalc.extend(list(r.booked_slots))
        r.status = "cancelled"
        r.slot_id = None
        r.booked_slots.clear()

    await db.flush()
    seen_slot_ids: set[uuid.UUID] = set()
    for s in slots_to_recalc:
        if s.id not in seen_slot_ids:
            seen_slot_ids.add(s.id)
            await _recalculate_slot_availability(db, s)

    await db.commit()
    for r in pending_items:
        await db.refresh(r, attribute_names=["session_type", "slot", "booked_slots"])

    if client_email:
        background_tasks.add_task(
            send_series_client_status_email,
            client_name=client_name,
            client_email=client_email,
            session_title=session_title,
            dates_list=dates_list,
            approved=False,
        )

    return pending_items


@router.get("", response_model=list[ReservationOut])
async def list_reservations(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
    from_date: date | None = Query(None, alias="from", description="Data inici (YYYY-MM-DD)"),
    to_date: date | None = Query(None, alias="to", description="Data fi (YYYY-MM-DD)"),
):
    """Llista reserves amb JOIN a session_types i slots (només admin/educador)."""
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
    current_user: dict = Depends(get_current_admin),
):
    """Actualitza estat, horari, compartició o camps de cobrament (preu / pagat) d'una reserva."""
    logger.info("PATCH /api/reservations/%s", reservation_id)

    reservation = await db.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found",
        )

    # Actualitzacions econòmiques internes
    if payload.price is not None:
        reservation.price = Decimal(str(round(payload.price, 2)))
    if payload.amount_paid is not None:
        reservation.amount_paid = Decimal(str(round(payload.amount_paid, 2)))

    schedule_changed = (
        payload.status is not None
        or payload.slot_id is not None
        or payload.is_shared is not None
    )

    if schedule_changed:
        # Estat previ per decidir si cal notificar al client
        was_already_confirmed = reservation.status == "confirmed"
        was_already_cancelled = reservation.status == "cancelled"
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
            if not all((s.is_available and not s.is_blocked) for s in new_slots):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Una o més franges necessàries per a la durada de la sessió no estan disponibles.",
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
                    end_time=end_time_str,
                )

        # Lògica d'enviament de correu de cancel·lació / rebuig al client
        is_now_cancelled = reservation.status == "cancelled"
        if is_now_cancelled and not was_already_cancelled and reservation.client_email:
            date_str = None
            start_time_str = None
            if old_slots:
                date_str = old_slots[0].date.strftime("%d/%m/%Y")
                start_time_str = old_slots[0].start_time.strftime("%H:%M")
            elif reservation.slot:
                date_str = reservation.slot.date.strftime("%d/%m/%Y")
                start_time_str = reservation.slot.start_time.strftime("%H:%M")

            background_tasks.add_task(
                send_client_cancellation_email,
                client_name=reservation.client_name,
                client_email=reservation.client_email,
                session_title=reservation.session_type.name,
                date_str=date_str,
                start_time=start_time_str,
            )

    await db.commit()
    await db.refresh(reservation, attribute_names=["session_type", "slot", "booked_slots"])

    return reservation
