from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import get_current_user
from app.config import get_settings
from app.database.models import User
from app.database.session import get_engine
from app.services.model_check import check_models, model_status

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health():
    settings = get_settings()
    checks = {}
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"
    try:
        from app.vectorstore.factory import get_vector_store

        get_vector_store()
        checks["vector_store"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["vector_store"] = f"error: {type(exc).__name__}"
    models = model_status()
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {
        "status": status,
        "version": "1.0.0",
        "environment": settings.environment,
        "llm_provider": settings.llm_provider,
        "vector_store": settings.vector_store,
        "checks": checks,
        "models": {"ok": models.get("ok"), "message": models.get("message")},
    }


@router.get("/settings")
def effective_settings(user: User = Depends(get_current_user)):
    """Non-secret effective configuration (for the Settings page)."""
    s = get_settings()
    return {
        "llm_provider": s.llm_provider,
        "chat_model": s.gemini_chat_model,
        "utility_model": s.gemini_utility_model,
        "embedding_model": s.gemini_embedding_model,
        "embedding_dimension": s.embedding_dimension,
        "vector_store": s.vector_store,
        "chunking": {"strategy": s.chunking_strategy, "chunk_size": s.chunk_size, "chunk_overlap": s.chunk_overlap,
                     "strategies": ["recursive", "token", "semantic", "structure"]},
        "retrieval": {"strategy": s.retrieval_strategy, "top_k": s.retrieval_top_k,
                      "similarity_threshold": s.similarity_threshold, "reranker": s.reranker,
                      "query_rewriting": s.enable_query_rewriting, "multi_query_count": s.multi_query_count,
                      "strategies": ["semantic", "hybrid", "mmr", "keyword"], "rerankers": ["none", "lexical", "llm"]},
        "upload": {"max_size_mb": s.max_upload_size_mb, "allowed_extensions": s.allowed_extensions},
        "model_status": model_status() if user.is_admin else {"ok": model_status().get("ok")},
    }


@router.post("/settings/check-models")
def recheck_models(user: User = Depends(get_current_user)):
    result = check_models(force=True)
    return result if user.is_admin else {"ok": result.get("ok"), "message": result.get("message")}
