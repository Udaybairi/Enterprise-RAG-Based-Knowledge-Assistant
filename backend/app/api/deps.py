"""Shared FastAPI dependencies: DB session, authentication, RBAC, audit context."""
from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database.models import Collection, Document, User
from app.database.repositories import AuditRepository, CollectionRepository
from app.database.session import get_db

bearer = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None or creds.scheme.lower() != "bearer":
        raise unauthorized
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise unauthorized from None
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        raise unauthorized
    request.state.user_id = user.id
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required")
    return user


def audit(db: Session, request: Request, user: User | None, action: str, resource_type: str | None = None,
          resource_id: str | None = None, **details) -> None:
    AuditRepository(db).log(action, user.id if user else None, resource_type, resource_id, details, client_ip(request))


def readable_collection(db: Session, user: User, collection_id: str) -> Collection:
    c = CollectionRepository(db).get(collection_id)
    if c is None or not CollectionRepository.can_read(user, c):
        # 404 (not 403) so that IDs of other tenants' collections are not disclosed
        raise HTTPException(status_code=404, detail="Collection not found")
    return c


def writable_collection(db: Session, user: User, collection_id: str) -> Collection:
    c = readable_collection(db, user, collection_id)
    if not CollectionRepository.can_write(user, c):
        raise HTTPException(status_code=403, detail="You do not have write access to this collection")
    return c


def readable_document(db: Session, user: User, document_id: str) -> Document:
    d = db.get(Document, document_id)
    if d is None or not CollectionRepository.can_read(user, d.collection):
        raise HTTPException(status_code=404, detail="Document not found")
    return d


def writable_document(db: Session, user: User, document_id: str) -> Document:
    d = readable_document(db, user, document_id)
    if not (user.is_admin or d.owner_id == user.id or d.collection.owner_id == user.id):
        raise HTTPException(status_code=403, detail="You do not have write access to this document")
    return d


def resolve_collection_ids(db: Session, user: User, requested: list[str] | None) -> list[str]:
    """Intersect the requested collections with what the user may read (all readable if none given)."""
    readable = CollectionRepository(db).readable_ids(user)
    if not requested:
        return readable
    allowed = set(readable)
    denied = [c for c in requested if c not in allowed]
    if denied:
        raise HTTPException(status_code=404, detail="One or more collections were not found")
    return list(dict.fromkeys(requested))
