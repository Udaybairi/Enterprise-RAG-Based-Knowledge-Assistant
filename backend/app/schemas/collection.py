from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[\w\s\-\.&()]+$")
    description: str = Field(default="", max_length=2000)
    visibility: str = Field(default="private", pattern="^(private|organization)$")


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120, pattern=r"^[\w\s\-\.&()]+$")
    description: str | None = Field(default=None, max_length=2000)
    visibility: str | None = Field(default=None, pattern="^(private|organization)$")


class CollectionOut(ORMModel):
    id: str
    name: str
    description: str
    visibility: str
    owner_id: str
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    chunk_count: int = 0
    size_bytes: int = 0
    can_write: bool = False
