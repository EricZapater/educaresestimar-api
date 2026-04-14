import uuid
from datetime import datetime

from pydantic import BaseModel


class SessionTypeOut(BaseModel):
    id: uuid.UUID
    name: str
    duration_minutes: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
