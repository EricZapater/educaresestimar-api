import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class ClientCustomPriceItem(BaseModel):
    session_type_id: uuid.UUID
    price: float = Field(ge=0)


class ClientCustomPriceOut(BaseModel):
    id: uuid.UUID
    session_type_id: uuid.UUID
    session_type_name: str | None = None
    price: float

    model_config = {"from_attributes": True}


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=30)
    email: EmailStr | None = None


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, min_length=1, max_length=30)
    email: EmailStr | None = None


class ClientPricesUpdate(BaseModel):
    prices: list[ClientCustomPriceItem]
    apply_to_unpaid_future: bool = False


class ClientOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: str
    email: str | None = None
    is_registered: bool = False
    total_sessions: int = 0
    pending_debt: float = 0.0
    custom_prices: list[ClientCustomPriceOut] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class ClientProfileOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: str
    email: str | None = None

    model_config = {"from_attributes": True}


class ClientProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, min_length=1, max_length=30)
    email: EmailStr | None = None
