"""Domain exceptions mapped to HTTP responses in ``main.py``."""
from __future__ import annotations


class AppError(Exception):
    status_code = 400

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class NotFoundError(AppError):
    status_code = 404


class ForbiddenError(AppError):
    status_code = 403


class ValidationFailedError(AppError):
    status_code = 422


class ConflictError(AppError):
    status_code = 409


class ProviderError(AppError):
    """Upstream LLM / embedding provider failure."""

    status_code = 502


class DocumentProcessingError(AppError):
    status_code = 422
