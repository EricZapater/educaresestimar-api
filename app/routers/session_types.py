import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.session_type import SessionType
from app.schemas.session_type import SessionTypeOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/session-types", tags=["Session Types"])


@router.get("", response_model=list[SessionTypeOut])
async def list_session_types(db: AsyncSession = Depends(get_db)):
    """Retorna la llista de tots els tipus de sessió."""
    logger.info("GET /api/session-types")
    result = await db.execute(select(SessionType).order_by(SessionType.name))
    return result.scalars().all()
