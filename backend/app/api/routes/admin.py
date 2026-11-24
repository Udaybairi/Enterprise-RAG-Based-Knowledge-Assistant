"""Administrative operations: data retention."""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import audit, require_admin
from app.config import get_settings
from app.database.models import User
from app.database.session import get_db
from app.services.retention import retention_status, run_retention

router = APIRouter(tags=["admin"])


@router.get("/api/admin/retention")
def get_retention(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return retention_status(db)


@router.post("/api/admin/retention/run")
def run_retention_now(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    result = run_retention(db)
    audit(db, request, admin, "retention.manual_run", "system", None, **result)
    db.commit()
    return result


@router.get("/api/cron/retention", include_in_schema=False)
def cron_retention(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Called daily by Vercel Cron, which sends ``Authorization: Bearer $CRON_SECRET``."""
    secret = get_settings().cron_secret
    if not secret or not authorization or not hmac.compare_digest(authorization, f"Bearer {secret}"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = run_retention(db)
    db.commit()
    return result
