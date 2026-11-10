"""SQLAlchemy engine / session management (PostgreSQL in prod, SQLite in dev/test)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import threading
from collections.abc import Callable

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_init_lock = threading.Lock()
_initialized = False
# Callables run once after tables are created (e.g. bootstrap admin). Registered by app.main.
init_hooks: list[Callable[[], None]] = []


def _build_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return engine
    # prepare_threshold=None disables server-side prepared statements, which break behind
    # transaction-mode poolers such as PgBouncer / Neon's pooled endpoint.
    connect_args = {"prepare_threshold": None} if "+psycopg" in url else {}
    if get_settings().serverless:
        # Function instances are frozen between invocations; don't keep idle connections around.
        return create_engine(url, poolclass=NullPool, connect_args=connect_args)
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20, connect_args=connect_args)


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        with _init_lock:
            if _engine is None:
                engine = _build_engine(get_settings().effective_database_url)
                _SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
                _engine = engine
    if not _initialized:
        init_db()
    return _engine


def reset_engine() -> None:
    """Dispose the engine (used by tests when switching databases)."""
    global _engine, _SessionLocal, _initialized
    if _engine is not None:
        _engine.dispose()
    _engine, _SessionLocal, _initialized = None, None, False


def init_db() -> None:
    """Create tables and run init hooks exactly once per process.

    Called lazily from ``get_engine`` so it also works on platforms that do not
    deliver ASGI lifespan events (some serverless runtimes).
    """
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        from app.database import models  # noqa: F401  (register models)

        Base.metadata.create_all(bind=_engine)
        _initialized = True
    for hook in init_hooks:
        hook()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session per request."""
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background jobs."""
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
