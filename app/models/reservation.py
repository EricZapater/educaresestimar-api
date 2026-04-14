import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'cancelled')",
            name="ck_reservation_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    client_name: Mapped[str] = mapped_column(Text, nullable=False)
    client_phone: Mapped[str] = mapped_column(Text, nullable=False)
    client_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session_types.id"),
        nullable=False,
    )
    slot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("available_slots.id"),
        nullable=True,
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
    )

    # Relationships for JOIN queries
    session_type = relationship("SessionType", lazy="joined")
    slot = relationship("Slot", lazy="joined")
