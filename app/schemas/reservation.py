import uuid
from datetime import datetime, date, time

from pydantic import BaseModel, Field, model_validator

from app.schemas.session_type import SessionTypeOut, SessionTypePublicOut
from app.schemas.slot import SlotOut


def compute_payment_status(price: float | None, amount_paid: float | None) -> str:
    p = float(price or 0.0)
    paid = float(amount_paid or 0.0)
    if p <= 0:
        return "paid" if paid >= 0 and p == 0 and paid > 0 else ("pending" if paid <= 0 else "paid")
    if paid <= 0:
        return "pending"
    if paid + 0.005 >= p:
        return "paid"
    return "partial"


class ReservationCreate(BaseModel):
    client_name: str = Field(alias="name")
    client_phone: str = Field(alias="phone")
    client_email: str | None = Field(default=None, alias="email")
    session_type_id: uuid.UUID
    slot_id: uuid.UUID | None = None
    message: str | None = None
    status: str | None = None
    is_shared: bool | None = None
    price: float | None = None

    model_config = {"populate_by_name": True}


class ReservationRecurringCreate(BaseModel):
    client_name: str = Field(alias="name")
    client_phone: str = Field(alias="phone")
    client_email: str | None = Field(default=None, alias="email")
    session_type_id: uuid.UUID
    start_date: date
    start_time: time
    recurrence: str  # "weekly" o "biweekly"
    occurrences: int = Field(default=1, ge=1, le=13)
    message: str | None = None
    is_shared: bool | None = None

    model_config = {"populate_by_name": True}


class ReservationUpdate(BaseModel):
    status: str | None = None
    slot_id: uuid.UUID | None = None
    is_shared: bool | None = None
    price: float | None = Field(default=None, ge=0)
    amount_paid: float | None = Field(default=None, ge=0)


class ClientReservationOut(BaseModel):
    """Schema segur per a respostes públiques i d'àrea de client (sense cap camp econòmic)."""
    id: uuid.UUID
    recurrence_group_id: uuid.UUID | None = None
    client_name: str = Field(serialization_alias="name")
    client_phone: str = Field(serialization_alias="phone")
    client_email: str | None = Field(default=None, serialization_alias="email")
    session_type_id: uuid.UUID
    slot_id: uuid.UUID | None = None
    message: str | None = None
    status: str
    is_shared: bool | None = None
    created_at: datetime
    session_type: SessionTypePublicOut | None = None
    slot: SlotOut | None = None
    booked_slots: list[SlotOut] = []

    model_config = {"from_attributes": True, "populate_by_name": True}


class ReservationOut(BaseModel):
    """Schema complet d'administrador amb camps de client i cobrament."""
    id: uuid.UUID
    client_id: uuid.UUID | None = None
    recurrence_group_id: uuid.UUID | None = None
    client_name: str = Field(serialization_alias="name")
    client_phone: str = Field(serialization_alias="phone")
    client_email: str | None = Field(default=None, serialization_alias="email")
    session_type_id: uuid.UUID
    slot_id: uuid.UUID | None = None
    message: str | None = None
    status: str
    is_shared: bool | None = None
    price: float | None = None
    amount_paid: float = 0.0
    payment_status: str = "pending"
    created_at: datetime
    session_type: SessionTypeOut | None = None
    slot: SlotOut | None = None
    booked_slots: list[SlotOut] = []

    model_config = {"from_attributes": True, "populate_by_name": True}

    @model_validator(mode="after")
    def set_payment_status(self) -> "ReservationOut":
        p = float(self.price or 0.0)
        paid = float(self.amount_paid or 0.0)
        if p == 0 and paid == 0:
            self.payment_status = "pending"
        elif paid <= 0:
            self.payment_status = "pending"
        elif paid + 0.005 >= p:
            self.payment_status = "paid"
        else:
            self.payment_status = "partial"
        return self


class RecurringCheckRequest(BaseModel):
    session_type_id: uuid.UUID
    start_slot_id: uuid.UUID
    recurrence: str  # "weekly" | "biweekly"
    occurrences: int = Field(default=4, ge=2, le=13)


class RecurringOccurrenceCheckOut(BaseModel):
    occurrence_index: int
    target_date: date
    target_time: time
    status: str  # "available" | "conflict"
    reason: str | None = None
    slot: SlotOut | None = None
    alternative_slots: list[SlotOut] = []


class RecurringCheckResponse(BaseModel):
    occurrences: list[RecurringOccurrenceCheckOut]
    has_conflicts: bool


class RecurringClientSubmitRequest(BaseModel):
    session_type_id: uuid.UUID
    slot_ids: list[uuid.UUID] = Field(min_length=1, max_length=13)
    message: str | None = None
