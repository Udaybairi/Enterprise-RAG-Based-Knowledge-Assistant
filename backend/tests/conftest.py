"""Test configuration: isolated temp data dir + SQLite DB, offline deterministic LLM/embeddings,
synchronous ingestion so API tests are deterministic."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="rag-tests-"))
os.environ.update({
    "ENVIRONMENT": "test",
    "LLM_PROVIDER": "fake",
    "DATA_DIR": str(_TMP / "data"),
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}"),
    "INGESTION_SYNC": "true",
    "RATE_LIMIT_ENABLED": "false",
    "SIMILARITY_THRESHOLD": "0.1",
    "VECTOR_STORE": os.environ.get("TEST_VECTOR_STORE", "chroma"),
    "EMBEDDING_DIMENSION": "256",
    "CHUNK_SIZE": "600",
    "CHUNK_OVERLAP": "80",
    "JWT_SECRET_KEY": "test-secret-key-that-is-long-enough-0123456789",
})
sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def tmp_dir() -> Path:
    d = _TMP / "files"
    d.mkdir(exist_ok=True)
    return d


def _register(client, email, password="Passw0rd!xyz", name="Test"):
    r = client.post("/api/auth/register", json={"email": email, "password": password, "full_name": name})
    if r.status_code == 409:
        r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code in (200, 201), r.text
    data = r.json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]


@pytest.fixture(scope="session")
def admin(client):
    return _register(client, "admin@acme.example", name="Admin")


@pytest.fixture(scope="session")
def alice(client, admin):
    return _register(client, "alice@acme.example", name="Alice")


@pytest.fixture(scope="session")
def bob(client, admin):
    return _register(client, "bob@acme.example", name="Bob")
