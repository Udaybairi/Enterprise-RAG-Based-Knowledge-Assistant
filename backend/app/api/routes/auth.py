from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import audit, get_current_user, require_admin
from app.config import get_settings
from app.core.rate_limit import rate_limit
from app.core.security import create_access_token, hash_password, verify_password
from app.database.models import Role, User
from app.database.repositories import CollectionRepository, UserRepository
from app.database.session import get_db
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserActiveUpdate,
    UserOut,
    UserRoleUpdate,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
users_router = APIRouter(prefix="/api/users", tags=["users"])


def _token(user: User) -> TokenResponse:
    token, exp = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, expires_in=exp, user=UserOut.model_validate(user))


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(rate_limit("auth"))])
def register(body: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    repo = UserRepository(db)
    first = repo.count() == 0
    if not settings.allow_registration and not first:
        raise HTTPException(status_code=403, detail="Self-registration is disabled")
    if repo.get_by_email(body.email):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    role = Role.admin.value if (first and settings.first_user_is_admin) else Role.user.value
    user = repo.create(body.email, hash_password(body.password), body.full_name.strip(), role)
    CollectionRepository(db).get_or_create_default(user)
    audit(db, request, user, "user.register", "user", user.id, role=role)
    db.commit()
    return _token(user)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit("auth"))])
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = UserRepository(db).get_by_email(body.email)
    if user is None or not verify_password(body.password, user.hashed_password):
        audit(db, request, None, "user.login_failed", "user", None, email=body.email)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    user.last_login_at = datetime.now(timezone.utc)
    audit(db, request, user, "user.login", "user", user.id)
    db.commit()
    return _token(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@users_router.get("", response_model=list[UserOut])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return UserRepository(db).list()


@users_router.patch("/{user_id}/role", response_model=UserOut)
def set_role(user_id: str, body: UserRoleUpdate, request: Request, admin: User = Depends(require_admin),
             db: Session = Depends(get_db)):
    target = UserRepository(db).get(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == admin.id and body.role != "admin":
        raise HTTPException(status_code=400, detail="You cannot remove your own admin role")
    target.role = body.role
    audit(db, request, admin, "user.role_changed", "user", target.id, role=body.role)
    db.commit()
    return target


@users_router.patch("/{user_id}/active", response_model=UserOut)
def set_active(user_id: str, body: UserActiveUpdate, request: Request, admin: User = Depends(require_admin),
               db: Session = Depends(get_db)):
    target = UserRepository(db).get(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate yourself")
    target.is_active = body.is_active
    audit(db, request, admin, "user.active_changed", "user", target.id, is_active=body.is_active)
    db.commit()
    return target
