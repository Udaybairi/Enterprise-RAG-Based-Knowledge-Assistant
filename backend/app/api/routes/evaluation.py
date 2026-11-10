from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import audit, get_current_user, require_admin
from app.chunking.factory import STRATEGIES
from app.database.models import EvaluationRun, User
from app.database.repositories import EvaluationRepository
from app.database.session import get_db
from app.evaluation.test_pipeline import load_dataset, run_and_store
from app.schemas.evaluation import EvaluationRequest, EvaluationRunOut
from app.services.jobs import submit

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])
RETRIEVAL = ("semantic", "hybrid", "mmr", "keyword")


@router.get("/dataset")
def dataset(_: User = Depends(get_current_user)):
    return load_dataset()


@router.post("/run", response_model=EvaluationRunOut, status_code=status.HTTP_202_ACCEPTED)
def run(body: EvaluationRequest, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not body.chunking_strategies or any(s not in STRATEGIES for s in body.chunking_strategies):
        raise HTTPException(status_code=422, detail=f"chunking_strategies must be a subset of {STRATEGIES}")
    if not body.retrieval_strategies or any(s not in RETRIEVAL for s in body.retrieval_strategies):
        raise HTTPException(status_code=422, detail=f"retrieval_strategies must be a subset of {RETRIEVAL}")
    stale = datetime.now(timezone.utc) - timedelta(hours=1)
    for r in db.query(EvaluationRun).filter(EvaluationRun.status == "running").all():
        created = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=timezone.utc)
        if created < stale:  # its worker died (e.g. a killed serverless function)
            r.status, r.error_message = "failed", "Evaluation did not finish (worker stopped)"
    db.flush()
    if db.query(EvaluationRun).filter(EvaluationRun.status == "running").count():
        raise HTTPException(status_code=409, detail="An evaluation is already running")
    run = EvaluationRun(created_by=admin.id, status="running", config=body.model_dump())
    db.add(run)
    audit(db, request, admin, "evaluation.run", "evaluation", run.id, **body.model_dump())
    db.commit()
    kwargs = dict(chunking_strategies=body.chunking_strategies, retrieval_strategies=body.retrieval_strategies,
                  top_k=body.top_k, evaluate_generation=body.evaluate_generation)
    submit(run_and_store, run.id, **kwargs)
    db.refresh(run)
    return run


@router.get("/runs", response_model=list[EvaluationRunOut])
def runs(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return EvaluationRepository(db).list()


@router.get("/runs/{run_id}", response_model=EvaluationRunOut)
def get_run(run_id: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = EvaluationRepository(db).get(run_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return r
