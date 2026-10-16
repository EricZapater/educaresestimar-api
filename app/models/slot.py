import uuid
from datetime import date, time, datetime

from sqlalchemy import Boolean, Date, Time, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Slot(Base):
    __tablename__ = "available_slots"
    __table_args__ = (
        UniqueConstraint("date", "start_time", name="uq_slot_date_start_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    is_blocked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    block_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )
