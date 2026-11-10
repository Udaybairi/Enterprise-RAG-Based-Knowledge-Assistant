"""Centralised application configuration.

Every tunable value is read from environment variables (or a ``.env`` file) so
that secrets are never hard-coded and deployments can be configured without
code changes.
"""
from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- application -------------------------------------------------------
    app_name: str = "Enterprise RAG Knowledge Assistant"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False
    # NoDecode: accept plain comma-separated values (as documented) as well as JSON lists.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    # Optional regex for additional allowed origins, e.g. Vercel preview URLs:
    #   ^https://my-frontend(-[a-z0-9-]+)?\.vercel\.app$
    cors_origin_regex: str | None = None

    # ---- runtime -----------------------------------------------------------
    # Serverless mode (Vercel, auto-detected via the VERCEL env var): no background threads
    # (documents are processed inside the upload request), no connection pooling inside the
    # function, and only /tmp is writable.
    serverless: bool = False
    # Documents stuck in "processing" longer than this (e.g. a killed function) may be re-processed.
    stale_processing_minutes: int = 15

    # ---- security ----------------------------------------------------------
    # No usable default in production: startup refuses to run with the dev key.
    jwt_secret_key: str = "dev-only-insecure-secret-change-me-please-0123456789"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8
    # The first account that registers becomes an admin when this is true.
    first_user_is_admin: bool = True
    allow_registration: bool = True
    # Optional bootstrap admin, created on startup if both are set.
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    # ---- rate limiting (requests per window per user / IP) -----------------
    rate_limit_enabled: bool = True
    rate_limit_default: int = 300
    rate_limit_chat: int = 30
    rate_limit_upload: int = 30
    rate_limit_auth: int = 20
    rate_limit_window_seconds: int = 60

    # ---- storage -----------------------------------------------------------
    # When unset, a SQLite file inside DATA_DIR is used (fine for development / single node).
    database_url: str | None = None
    data_dir: Path = BACKEND_DIR / "data"
    # Where original uploaded files live: "local" (DATA_DIR/uploads) or "database" (Postgres BYTEA;
    # required on serverless platforms that have no persistent disk).
    file_storage: Literal["local", "database"] = "local"
    max_upload_size_mb: int = 50
    allowed_extensions: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [".pdf", ".docx", ".txt", ".csv", ".xlsx", ".pptx", ".md", ".markdown"]
    )

    # ---- LLM provider ------------------------------------------------------
    # "gemini" for real usage; "fake" is a deterministic offline provider used
    # by the test-suite and for running the stack without an API key.
    llm_provider: Literal["gemini", "fake"] = "gemini"
    google_api_key: str | None = None
    gemini_chat_model: str = "gemini-flash-latest"
    # Small/fast model used for query rewriting, expansion and LLM reranking.
    gemini_utility_model: str = "gemini-flash-lite-latest"
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dimension: int = 768
    generation_temperature: float = 0.1
    generation_max_output_tokens: int = 2048
    llm_timeout_seconds: int = 120

    # ---- embeddings --------------------------------------------------------
    embedding_batch_size: int = 50
    embedding_max_retries: int = 6
    embedding_requests_per_minute: int = 1200

    # ---- vector store ------------------------------------------------------
    # chroma / faiss: local disk. pgvector: PostgreSQL with the pgvector extension (serverless-friendly).
    vector_store: Literal["faiss", "chroma", "pgvector"] = "chroma"

    # ---- chunking ----------------------------------------------------------
    chunking_strategy: Literal["recursive", "token", "semantic", "structure"] = "structure"
    chunk_size: int = 1000
    chunk_overlap: int = 150
    semantic_breakpoint_percentile: float = 90.0
    semantic_buffer_size: int = 1

    # ---- retrieval ---------------------------------------------------------
    retrieval_strategy: Literal["semantic", "hybrid", "mmr", "keyword"] = "hybrid"
    retrieval_top_k: int = 6
    retrieval_fetch_k: int = 24
    similarity_threshold: float = 0.45
    mmr_lambda: float = 0.6
    hybrid_alpha: float = 0.6  # weight of the vector ranking in fusion
    reranker: Literal["none", "lexical", "llm"] = "lexical"
    multi_query_count: int = 3
    enable_query_rewriting: bool = True
    max_context_tokens: int = 12000

    @field_validator("cors_origins", "allowed_extensions", mode="before")
    @classmethod
    def _split_csv(cls, v):  # allow comma separated env values
        if isinstance(v, str):
            if v.strip().startswith("["):
                import json

                return json.loads(v)
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @model_validator(mode="after")
    def _serverless_defaults(self):
        if os.getenv("VERCEL"):
            self.serverless = True
        if self.serverless and str(self.data_dir).startswith(str(BACKEND_DIR)):
            # the deployment bundle is read-only on serverless platforms; only /tmp is writable
            self.data_dir = Path(tempfile.gettempdir()) / "rag-data"
        return self

    @property
    def effective_database_url(self) -> str:
        url = self.database_url or f"sqlite:///{self.data_dir / 'app.db'}"
        # Hosted Postgres providers (Neon, Vercel, Heroku...) hand out postgres:// URLs;
        # SQLAlchemy needs the driver spelled out.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def vectors_dir(self) -> Path:
        return self.data_dir / "vectors"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.uploads_dir, self.vectors_dir):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
