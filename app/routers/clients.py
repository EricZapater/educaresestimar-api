import logging
import uuid
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.auth import get_current_admin
from app.database import get_db
from app.models.client import Client, ClientSessionPrice
from app.models.reservation import Reservation
from app.models.session_type import SessionType
from app.schemas.client import (
    ClientCreate,
    ClientCustomPriceOut,
    ClientOut,
    ClientPricesUpdate,
    ClientUpdate,
)
from app.utils import normalize_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/clients", tags=["Clients (Admin)"])


async def _build_client_out(client: Client, client_reservations: list[Reservation]) -> ClientOut:
    today_madrid = datetime.now(ZoneInfo("Europe/Madrid")).date()
    total_sessions = 0
    pending_debt = 0.0

    for r in client_reservations:
        if r.status != "confirmed":
            continue
        total_sessions += 1
        r_slot = (
            sorted(r.booked_slots, key=lambda s: s.start_time)[0]
            if r.booked_slots
            else r.slot
        )
        r_date = r_slot.date if r_slot else r.created_at.date()
        if r_date <= today_madrid:
            price_val = float(r.price or 0.0)
            paid_val = float(r.amount_paid or 0.0)
            if price_val > paid_val:
                pending_debt += price_val - paid_val

    custom_out = [
        ClientCustomPriceOut(
            id=cp.id,
            session_type_id=cp.session_type_id,
            session_type_name=cp.session_type.name if cp.session_type else None,
            price=float(cp.price),
        )
        for cp in (client.custom_prices or [])
    ]

    return ClientOut(
        id=client.id,
        name=client.name,
        phone=client.phone,
        email=client.email,
        is_registered=bool(client.password_hash),
        total_sessions=total_sessions,
        pending_debt=round(pending_debt, 2),
        custom_prices=custom_out,
        created_at=client.created_at,
    )


@router.get("", response_model=list[ClientOut])
async def list_clients(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Llista tots els clients amb el recompte de sessions, deute exigible i tarifes personalitzades."""
    clients_res = await db.execute(
        select(Client)
        .options(selectinload(Client.custom_prices).joinedload(ClientSessionPrice.session_type))
        .order_by(func.lower(Client.name))
    )
    clients = list(clients_res.scalars().unique().all())

    res_query = await db.execute(
        select(Reservation)
        .options(joinedload(Reservation.slot), selectinload(Reservation.booked_slots))
        .where(Reservation.client_id.is_not(None), Reservation.status == "confirmed")
    )
    all_confirmed = list(res_query.scalars().unique().all())
    by_client: dict[uuid.UUID, list[Reservation]] = {}
    for r in all_confirmed:
        if r.client_id:
            by_client.setdefault(r.client_id, []).append(r)

    return [await _build_client_out(c, by_client.get(c.id, [])) for c in clients]


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: ClientCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Crea manualment una fitxa de client des de l'administració."""
    email_norm = normalize_email(str(payload.email) if payload.email else None)
    if email_norm:
        dup = await db.execute(select(Client).where(func.lower(Client.email) == email_norm))
        if dup.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ja existeix un client amb aquest correu electrònic.",
            )

    client = Client(
        name=payload.name.strip(),
        phone=payload.phone.strip(),
        email=email_norm,
    )
    db.add(client)
    await db.flush()
    await db.refresh(client, attribute_names=["custom_prices"])
    return await _build_client_out(client, [])


@router.patch("/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: uuid.UUID,
    payload: ClientUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Actualitza les dades bàsiques d'un client."""
    client = await db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client no trobat")

    if payload.email is not None:
        email_norm = normalize_email(str(payload.email))
        if email_norm and email_norm != client.email:
            dup = await db.execute(
                select(Client).where(func.lower(Client.email) == email_norm, Client.id != client_id)
            )
            if dup.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Aquest correu electrònic ja pertany a un altre client.",
                )
        client.email = email_norm

    if payload.name is not None:
        client.name = payload.name.strip()
    if payload.phone is not None:
        client.phone = payload.phone.strip()

    await db.flush()

    res_query = await db.execute(
        select(Reservation)
        .options(joinedload(Reservation.slot), selectinload(Reservation.booked_slots))
        .where(Reservation.client_id == client_id, Reservation.status == "confirmed")
    )
    c_res = list(res_query.scalars().unique().all())
    await db.refresh(client, attribute_names=["custom_prices"])
    return await _build_client_out(client, c_res)


@router.put("/{client_id}/prices", response_model=ClientOut)
async def update_client_prices(
    client_id: uuid.UUID,
    payload: ClientPricesUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Desa les tarifes personalitzades per tipus de sessió d'un client."""
    res = await db.execute(
        select(Client)
        .options(selectinload(Client.custom_prices))
        .where(Client.id == client_id)
    )
    client = res.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client no trobat")

    # Esborrar tarifes actuals i inserir les noves definides
    client.custom_prices.clear()
    await db.flush()

    price_map: dict[uuid.UUID, Decimal] = {}
    for item in payload.prices:
        st = await db.get(SessionType, item.session_type_id)
        if st is None:
            continue
        dec_price = Decimal(str(round(item.price, 2)))
        price_map[item.session_type_id] = dec_price
        cp = ClientSessionPrice(
            client_id=client.id,
            session_type_id=item.session_type_id,
            price=dec_price,
        )
        db.add(cp)

    await db.flush()

    # Opcionalment aplicar a reserves futures pendents de cobrar
    if payload.apply_to_unpaid_future and price_map:
        today_madrid = datetime.now(ZoneInfo("Europe/Madrid")).date()
        fut_res = await db.execute(
            select(Reservation)
            .options(joinedload(Reservation.slot), selectinload(Reservation.booked_slots))
            .where(
                Reservation.client_id == client_id,
                Reservation.status != "cancelled",
                Reservation.amount_paid == 0,
            )
        )
        for r in fut_res.scalars().unique().all():
            r_slot = r.booked_slots[0] if r.booked_slots else r.slot
            if r_slot and r_slot.date >= today_madrid and r.session_type_id in price_map:
                r.price = price_map[r.session_type_id]

    await db.flush()
    refreshed_res = await db.execute(
        select(Client)
        .options(selectinload(Client.custom_prices).joinedload(ClientSessionPrice.session_type))
        .where(Client.id == client_id)
    )
    refreshed_client = refreshed_res.scalar_one()

    res_query = await db.execute(
        select(Reservation)
        .options(joinedload(Reservation.slot), selectinload(Reservation.booked_slots))
        .where(Reservation.client_id == client_id, Reservation.status == "confirmed")
    )
    c_res = list(res_query.scalars().unique().all())
    return await _build_client_out(refreshed_client, c_res)
