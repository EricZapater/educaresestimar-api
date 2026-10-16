import asyncio
import logging
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from app.database import async_session
from app.models.admin_user import AdminUser
from app.models.reservation import Reservation
from app.models.slot import Slot
from app.email import send_daily_agenda_email

logger = logging.getLogger(__name__)

CA_DAYS = ["Dilluns", "Dimarts", "Dimecres", "Dijous", "Divendres", "Dissabte", "Diumenge"]
CA_MONTHS = [
    "", "de gener", "de febrer", "de març", "d'abril", "de maig", "de juny",
    "de juliol", "d'agost", "de setembre", "d'octubre", "de novembre", "de desembre"
]


def _format_catalan_date(d: date) -> str:
    day_name = CA_DAYS[d.weekday()]
    month_name = CA_MONTHS[d.month]
    return f"{day_name} {d.day} {month_name} de {d.year}"


async def generate_and_send_daily_agenda(target_date: date):
    """Consulta l'agenda del dia target_date i envia el correu resum als administradors/educador."""
    async with async_session() as db:
        # 1. Obtenir administradors
        admins_res = await db.execute(select(AdminUser.email))
        admin_emails = list(admins_res.scalars().all())
        if not admin_emails:
            logger.info("Cap usuari administrador trobat per enviar l'agenda diària.")
            return

        # 2. Obtenir reserves confirmades amb slots del dia
        res_query = (
            select(Reservation)
            .options(
                joinedload(Reservation.session_type),
                joinedload(Reservation.slot),
                selectinload(Reservation.booked_slots),
            )
            .where(Reservation.status == "confirmed")
        )
        res_result = await db.execute(res_query)
        all_confirmed = list(res_result.scalars().unique().all())

        confirmed_today: list[tuple[time, dict]] = []
        for r in all_confirmed:
            slots_for_r = sorted(r.booked_slots, key=lambda s: s.start_time) if r.booked_slots else ([r.slot] if r.slot else [])
            today_slots = [s for s in slots_for_r if s and s.date == target_date]
            if not today_slots:
                continue

            start_t = today_slots[0].start_time
            end_t = today_slots[-1].end_time
            confirmed_today.append(
                (
                    start_t,
                    {
                        "time_range": f"{start_t.strftime('%H:%M')} - {end_t.strftime('%H:%M')}",
                        "client_name": r.client_name,
                        "client_phone": r.client_phone,
                        "session_title": r.session_type.name if r.session_type else "Sessió",
                        "is_shared": bool(r.is_shared or (r.session_type and r.session_type.is_shared)),
                        "message": r.message,
                    },
                )
            )

        confirmed_today.sort(key=lambda x: x[0])
        confirmed_items = [item for _, item in confirmed_today]

        # 3. Obtenir franges bloquejades manualment per avui i agrupar les consecutives amb el mateix motiu
        blocked_query = (
            select(Slot)
            .where(Slot.date == target_date, Slot.is_blocked.is_(True))
            .order_by(Slot.start_time)
        )
        blocked_res = await db.execute(blocked_query)
        blocked_slots = list(blocked_res.scalars().all())

        blocked_items: list[dict] = []
        for s in blocked_slots:
            reason = s.block_reason or "No disponible"
            if (
                blocked_items
                and blocked_items[-1]["_end_time"] == s.start_time
                and blocked_items[-1]["reason"] == reason
            ):
                blocked_items[-1]["_end_time"] = s.end_time
                blocked_items[-1]["time_range"] = f"{blocked_items[-1]['_start_str']} - {s.end_time.strftime('%H:%M')}"
            else:
                blocked_items.append(
                    {
                        "_start_str": s.start_time.strftime("%H:%M"),
                        "_end_time": s.end_time,
                        "time_range": f"{s.start_time.strftime('%H:%M')} - {s.end_time.strftime('%H:%M')}",
                        "reason": reason,
                    }
                )

        # 4. Obtenir sol·licituds pendents de validació (globals)
        pending_query = (
            select(Reservation)
            .options(
                joinedload(Reservation.session_type),
                joinedload(Reservation.slot),
                selectinload(Reservation.booked_slots),
            )
            .where(Reservation.status == "pending")
            .order_by(Reservation.created_at.desc())
        )
        pending_res = await db.execute(pending_query)
        all_pending = list(pending_res.scalars().unique().all())

        pending_items: list[dict] = []
        for p in all_pending:
            p_slot = p.slot or (p.booked_slots[0] if p.booked_slots else None)
            slot_info = (
                f"{p_slot.date.strftime('%d/%m/%Y')} · {p_slot.start_time.strftime('%H:%M')}"
                if p_slot
                else "Sense horari"
            )
            pending_items.append(
                {
                    "client_name": p.client_name,
                    "client_phone": p.client_phone,
                    "session_title": p.session_type.name if p.session_type else "Sessió",
                    "slot_info": slot_info,
                }
            )

        date_formatted = _format_catalan_date(target_date)
        await asyncio.to_thread(
            send_daily_agenda_email,
            date_formatted=date_formatted,
            confirmed_items=confirmed_items,
            pending_items=pending_items,
            blocked_items=blocked_items,
            admin_emails=admin_emails,
        )


async def daily_agenda_scheduler_loop():
    """Bucle en segon pla que s'executa cada matí a les 08:00h (Europe/Madrid) de dilluns a divendres."""
    tz = ZoneInfo("Europe/Madrid")
    logger.info("Daily agenda scheduler started (08:00 Europe/Madrid, Mon-Fri).")

    while True:
        try:
            now = datetime.now(tz)
            target = now.replace(hour=8, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)

            wait_seconds = (target - now).total_seconds()
            logger.info(
                "Next daily agenda check scheduled for %s (in %.0f seconds).",
                target.strftime("%Y-%m-%d %H:%M %Z"),
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)

            today_local = datetime.now(tz).date()
            # Només de dilluns (0) a divendres (4)
            if today_local.weekday() < 5:
                logger.info("Triggering 08:00 daily agenda email for %s", today_local)
                await generate_and_send_daily_agenda(today_local)
            else:
                logger.info("Skipping daily agenda email on weekend (%s).", today_local)

            # Esperar uns segons per evitar doble execució en el mateix minut
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("Daily agenda scheduler stopped.")
            break
        except Exception as e:
            logger.error("Error in daily agenda scheduler loop: %s", str(e))
            await asyncio.sleep(60)
