import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.reservation import Reservation
from app.models.session_type import SessionType
from app.schemas.session_type import SessionTypeCreate, SessionTypeOut, SessionTypeUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/session-types", tags=["Session Types"])


@router.get("", response_model=list[SessionTypeOut])
async def list_session_types(db: AsyncSession = Depends(get_db)):
    """Retorna la llista de tots els tipus de sessió."""
    logger.info("GET /api/session-types")
    result = await db.execute(select(SessionType).order_by(SessionType.name))
    return result.scalars().all()


@router.post("", response_model=SessionTypeOut, status_code=status.HTTP_201_CREATED)
async def create_session_type(
    payload: SessionTypeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Crea un nou tipus de sessió."""
    logger.info("POST /api/session-types name=%s", payload.name)
    session_type = SessionType(
        name=payload.name,
        duration_minutes=payload.duration_minutes,
        is_shared=payload.is_shared,
        max_clients=payload.max_clients,
        description=payload.description,
    )
    db.add(session_type)
    await db.flush()
    await db.refresh(session_type)
    return session_type


@router.patch("/{session_type_id}", response_model=SessionTypeOut)
async def update_session_type(
    session_type_id: uuid.UUID,
    payload: SessionTypeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Actualitza un tipus de sessió existent."""
    logger.info("PATCH /api/session-types/%s", session_type_id)
    session_type = await db.get(SessionType, session_type_id)
    if session_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session type not found",
        )

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(session_type, key, value)

    await db.flush()
    await db.refresh(session_type)
    return session_type


@router.delete("/{session_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session_type(
    session_type_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Elimina un tipus de sessió. Retorna 409 si té reserves actives associades."""
    logger.info("DELETE /api/session-types/%s", session_type_id)
    session_type = await db.get(SessionType, session_type_id)
    if session_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session type not found",
        )

    # Check for active reservations using this session type
    active_res = await db.execute(
        select(Reservation.id).where(
            Reservation.session_type_id == session_type_id,
            Reservation.status != "cancelled",
        ).limit(1)
    )
    if active_res.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete session type with active reservations",
        )

    await db.delete(session_type)
