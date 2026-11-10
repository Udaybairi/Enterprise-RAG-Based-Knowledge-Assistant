from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class RetrievalOptions(BaseModel):
    top_k: int | None = Field(default=None, ge=1, le=30)
    similarity_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    strategy: Literal["semantic", "hybrid", "mmr", "keyword"] | None = None
    reranker: Literal["none", "lexical", "llm"] | None = None
    use_query_rewriting: bool | None = None
    multi_query: bool | None = None
    document_ids: list[str] | None = None
    file_types: list[str] | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    collection_ids: list[str] | None = None
    stream: bool = True
    options: RetrievalOptions = Field(default_factory=RetrievalOptions)
    regenerate: bool = False  # replace the last assistant answer for this question


class Citation(BaseModel):
    index: int
    chunk_id: str
    document_id: str
    document_name: str
    file_type: str | None = None
    page_number: int | None = None
    section: str | None = None
    snippet: str
    score: float | None = None
    collection_id: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    message_id: str
    answer: str
    citations: list[Citation]
    grounded: bool
    rewritten_query: str | None = None
    latency_ms: float
    retrieval: dict[str, Any] = {}


class MessageOut(ORMModel):
    id: str
    role: str
    content: str
    citations: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    feedback: int = 0
    created_at: datetime


class ConversationSummary(ORMModel):
    id: str
    title: str
    collection_ids: list[str] = []
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut] = []


class FeedbackRequest(BaseModel):
    rating: int = Field(ge=-1, le=1)
    comment: str | None = Field(default=None, max_length=2000)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    collection_ids: list[str] | None = None
    options: RetrievalOptions = Field(default_factory=RetrievalOptions)


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    collection_id: str
    page_number: int | None
    section: str | None
    text: str
    score: float
    vector_score: float | None = None
    keyword_score: float | None = None


class SearchResponse(BaseModel):
    query: str
    queries: list[str]
    hits: list[SearchHit]
    latency_ms: float
