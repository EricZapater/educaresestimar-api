import uuid
from datetime import date, time, datetime

from pydantic import BaseModel


class SlotCreate(BaseModel):
    date: date
    start_time: time
    end_time: time


class SlotOut(BaseModel):
    id: uuid.UUID
    date: date
    start_time: time
    end_time: time
    is_available: bool
    created_at: datetime

    model_config = {"from_attributes": True}
