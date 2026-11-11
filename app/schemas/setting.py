from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

KEY_PATTERN = r"^[a-z0-9][a-z0-9_.-]{0,99}$"


class SettingCreate(BaseModel):
    key: str = Field(pattern=KEY_PATTERN, description="lowercase letters, digits, '_', '.', '-'")
    value: str = Field(min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=300)


class SettingUpdate(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=300)

    @field_validator("value")
    @classmethod
    def _not_null(cls, v):
        if v is None:
            raise ValueError("must not be null")
        return v


class SettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: str
    description: str | None
    updated_at: datetime
    updated_by_id: int | None


class PublicInfo(BaseModel):
    company_name: str
    registration_open: bool
