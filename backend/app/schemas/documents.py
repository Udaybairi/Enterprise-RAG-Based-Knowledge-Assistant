from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import ORMModel


class DocumentOut(ORMModel):
    id: str
    collection_id: str
    owner_id: str
    filename: str
    file_type: str
    mime_type: str
    size_bytes: int
    status: str
    error_message: str | None = None
    page_count: int
    chunk_count: int
    chunking_strategy: str | None = None
    embedding_model: str | None = None
    vector_store: str | None = None
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None = None


class ProcessingLogOut(ORMModel):
    id: int
    level: str
    stage: str
    message: str
    duration_ms: float | None = None
    created_at: datetime


class DocumentDetail(DocumentOut):
    meta: dict[str, Any] = {}
    logs: list[ProcessingLogOut] = []
    collection_name: str | None = None


class DocumentList(BaseModel):
    items: list[DocumentOut]
    total: int


class UploadResult(BaseModel):
    documents: list[DocumentOut]
    rejected: list[dict[str, str]] = []


class ReprocessRequest(BaseModel):
    chunking_strategy: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None


class ChunkOut(ORMModel):
    id: str
    chunk_index: int
    text: str
    page_number: int | None = None
    section: str | None = None
    token_count: int


class DocumentPreview(BaseModel):
    document_id: str
    filename: str
    page: int | None
    page_count: int
    chunks: list[ChunkOut]
