from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import MAX_PASSWORD_BYTES
from app.models.enums import UserRole


def _password_fits_bcrypt(v: str) -> str:
    if len(v.encode()) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes (non-ASCII characters use several)")
    return v


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=MAX_PASSWORD_BYTES)
    role: UserRole = UserRole.EMPLOYEE

    _bcrypt_limit = field_validator("password")(_password_fits_bcrypt)

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    password: str | None = Field(default=None, min_length=8, max_length=MAX_PASSWORD_BYTES)
    role: UserRole | None = None
    is_active: bool | None = None
    unlock: bool | None = None  # admin: clear a login lockout

    @field_validator("full_name", "password", "role", "is_active", "unlock")
    @classmethod
    def _not_null(cls, v, info):
        if v is None:
            raise ValueError("must not be null")
        return _password_fits_bcrypt(v) if isinstance(v, str) and info.field_name == "password" else v


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=MAX_PASSWORD_BYTES)

    _bcrypt_limit = field_validator("new_password")(_password_fits_bcrypt)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class UserList(BaseModel):
    items: list[UserOut]
    total: int
    skip: int
    limit: int


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
