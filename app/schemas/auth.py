import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=30)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=6, max_length=128)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None = None
    phone: str | None = None
    role: str = "admin"

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    token: str
    role: str = "admin"
    user: UserResponse
    expires_at: datetime
