"""Vercel entrypoint: the Python runtime serves the ASGI ``app`` defined here.

vercel.json rewrites every request to this function, so the FastAPI routes
(/api/...) work unchanged.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402,F401
