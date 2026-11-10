"""FastAPI application entry point."""
from __future__ import annotations

import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import auth, chat, collections, dashboard, documents, evaluation, health, search
from app.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger, request_id_var, setup_logging
from app.core.security import hash_password
from app.database.models import Role
from app.database.repositories import CollectionRepository, UserRepository
from app.database.session import get_engine, init_hooks, session_scope

log = get_logger("app")
_INSECURE_DEFAULT_SECRET = "dev-only-insecure-secret-change-me-please-0123456789"


def _check_secrets() -> None:
    s = get_settings()
    if s.environment == "production" and (s.jwt_secret_key == _INSECURE_DEFAULT_SECRET or len(s.jwt_secret_key) < 32):
        raise RuntimeError("JWT_SECRET_KEY must be set to a strong secret (>= 32 chars) in production")


def _bootstrap_admin() -> None:
    s = get_settings()
    if not (s.bootstrap_admin_email and s.bootstrap_admin_password):
        return
    with session_scope() as db:
        repo = UserRepository(db)
        if repo.get_by_email(s.bootstrap_admin_email):
            return
        user = repo.create(s.bootstrap_admin_email, hash_password(s.bootstrap_admin_password), "Administrator",
                           Role.admin.value)
        CollectionRepository(db).get_or_create_default(user)
        log.info("Bootstrap admin %s created", s.bootstrap_admin_email)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_logging(s.log_level, s.log_json)
    _check_secrets()
    if s.llm_provider == "gemini" and not s.google_api_key:
        log.warning("GOOGLE_API_KEY is not set: ingestion and chat will fail until it is configured "
                    "(or set LLM_PROVIDER=fake for an offline demo).")
    get_engine()  # creates tables and runs init hooks (bootstrap admin) once
    from app.services.jobs import requeue_unfinished, shutdown
    from app.services.model_check import check_models

    if not s.serverless:
        # Long-lived server: resume interrupted jobs and verify models in the background.
        # Serverless: no background work outlives a request; models are verified on demand.
        requeue_unfinished()
        if s.environment != "test":
            threading.Thread(target=check_models, daemon=True, name="model-check").start()
    log.info("%s started (provider=%s, vector_store=%s)", s.app_name, s.llm_provider, s.vector_store)
    yield
    shutdown()


# Also run on first database use, for runtimes that do not deliver ASGI lifespan events.
init_hooks.extend([_check_secrets, _bootstrap_admin])


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title=s.app_name, version="1.0.0", lifespan=lifespan,
        description="Enterprise Retrieval-Augmented Generation knowledge assistant API",
        docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origins, allow_origin_regex=s.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        ms = (time.perf_counter() - t0) * 1000
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path != "/api/health":
            log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path, response.status_code, ms)
        return response

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": "Validation failed", "errors": errors})

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error: %s", exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    for r in (health.router, auth.router, auth.users_router, collections.router, documents.router, chat.router,
              search.router, dashboard.router, evaluation.router):
        app.include_router(r)
    return app


app = create_app()
