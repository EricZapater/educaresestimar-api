import uuid
from datetime import date, time, datetime

from pydantic import BaseModel, Field


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
    is_blocked: bool = False
    block_reason: str | None = None
    current_occupants: int = 0
    is_shared_occupied: bool = False
    max_clients: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SlotBulkCreate(BaseModel):
    slots: list[SlotCreate]


class SlotBlockRange(BaseModel):
    date: date
    start_time: time
    end_time: time
    reason: str | None = None


class SlotUnblockRange(BaseModel):
    date: date
    start_time: time
    end_time: time | None = None


class SlotReplicateWeek(BaseModel):
    source_week_start: date
    weeks_ahead: int = Field(default=4, ge=1, le=12)


