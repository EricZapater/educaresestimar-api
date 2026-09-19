import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SessionType(Base):
    __tablename__ = "session_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_shared: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    max_clients: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )
