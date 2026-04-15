import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.session_type import SessionTypeOut
from app.schemas.slot import SlotOut


class ReservationCreate(BaseModel):
    client_name: str = Field(alias="name")
    client_phone: str = Field(alias="phone")
    client_email: str | None = Field(default=None, alias="email")
    session_type_id: uuid.UUID
    slot_id: uuid.UUID | None = None
    message: str | None = None

    model_config = {"populate_by_name": True}


class ReservationUpdate(BaseModel):
    status: str | None = None
    slot_id: uuid.UUID | None = None


class ReservationOut(BaseModel):
    id: uuid.UUID
    client_name: str = Field(serialization_alias="name")
    client_phone: str = Field(serialization_alias="phone")
    client_email: str | None = Field(default=None, serialization_alias="email")
    session_type_id: uuid.UUID
    slot_id: uuid.UUID | None = None
    message: str | None = None
    status: str
    created_at: datetime
    session_type: SessionTypeOut | None = None
    slot: SlotOut | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}
