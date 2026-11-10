from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class EvaluationRequest(BaseModel):
    chunking_strategies: list[str] = Field(default_factory=lambda: ["recursive", "structure", "semantic"])
    retrieval_strategies: list[str] = Field(default_factory=lambda: ["semantic", "hybrid", "mmr"])
    top_k: int = Field(default=4, ge=1, le=20)
    evaluate_generation: bool = True


class EvaluationRunOut(ORMModel):
    id: str
    status: str
    config: dict[str, Any]
    results: dict[str, Any]
    error_message: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
