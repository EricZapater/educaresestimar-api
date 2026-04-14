import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.session_type import SessionTypeOut
from app.schemas.slot import SlotOut


class ReservationCreate(BaseModel):
    client_name: str
    client_phone: str
    client_email: str | None = None
    session_type_id: uuid.UUID
    slot_id: uuid.UUID | None = None
    message: str | None = None


class ReservationCreated(BaseModel):
    id: uuid.UUID
    status: str


class ReservationUpdate(BaseModel):
    status: str | None = None
    slot_id: uuid.UUID | None = None


class ReservationOut(BaseModel):
    id: uuid.UUID
    client_name: str
    client_phone: str
    client_email: str | None = None
    session_type_id: uuid.UUID
    slot_id: uuid.UUID | None = None
    message: str | None = None
    status: str
    created_at: datetime
    session_type: SessionTypeOut | None = None
    slot: SlotOut | None = None

    model_config = {"from_attributes": True}
