import uuid
from datetime import datetime

from pydantic import BaseModel


class SessionTypeCreate(BaseModel):
    name: str
    duration_minutes: int | None = None
    is_shared: bool = False
    max_clients: int = 1
    description: str | None = None
    default_price: float = 0.0


class SessionTypeUpdate(BaseModel):
    name: str | None = None
    duration_minutes: int | None = None
    is_shared: bool | None = None
    max_clients: int | None = None
    description: str | None = None
    default_price: float | None = None


class SessionTypePublicOut(BaseModel):
    id: uuid.UUID
    name: str
    duration_minutes: int | None = None
    is_shared: bool = False
    max_clients: int = 1
    description: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionTypeOut(SessionTypePublicOut):
    default_price: float = 0.0
