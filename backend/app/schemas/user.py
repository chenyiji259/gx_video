from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    username: str = Field(..., max_length=64)


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=128)


class UserLogin(BaseModel):
    username: str
    password: str


class UserUpdate(BaseModel):
    password: Optional[str] = Field(None, min_length=6, max_length=128)
    # Extensible for avatar_url, etc. later


class UserResponse(UserBase):
    id: str
    status: str
    credits: int
    plan_type: str
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
