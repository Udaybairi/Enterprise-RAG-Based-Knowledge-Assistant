from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import (
    audit,
    get_current_user,
    readable_document,
    resolve_collection_ids,
    writable_collection,
    writable_document,
)
from app.chunking.factory import STRATEGIES
from app.config import get_settings
from app.core.exceptions import AppError
from app.core.rate_limit import rate_limit
from app.database.models import User
from app.database.repositories import ChunkRepository, CollectionRepository, DocumentRepository
from app.database.session import get_db
from app.schemas.documents import (
    ChunkOut,
    DocumentDetail,
    DocumentList,
    DocumentOut,
    DocumentPreview,
    ProcessingLogOut,
    ReprocessRequest,
    UploadResult,
)
from app.services import document_service, file_storage

router = APIRouter(prefix="/api/documents", tags=["documents"])
MAX_FILES_PER_REQUEST = 20


@router.post("/upload", response_model=UploadResult, status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(rate_limit("upload"))])
async def upload_documents(
    request: Request,
    files: list[UploadFile] = File(...),
    collection_id: str | None = Form(default=None),
    chunking_strategy: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(status_code=400, detail=f"At most {MAX_FILES_PER_REQUEST} files per upload")
    if chunking_strategy and chunking_strategy not in STRATEGIES:
        raise HTTPException(status_code=422, detail=f"chunking_strategy must be one of {STRATEGIES}")
    collection = (writable_collection(db, user, collection_id) if collection_id
                  else CollectionRepository(db).get_or_create_default(user))
    limit = get_settings().max_upload_bytes
    created, rejected = [], []
    for f in files:
        name = f.filename or "document"
        data = await f.read(limit + 1)
        try:
            doc = document_service.create_document(db, user, collection, name, data)
            created.append(doc)
        except AppError as exc:
            rejected.append({"filename": name, "reason": exc.message})
        finally:
            await f.close()
    for d in created:
        audit(db, request, user, "document.upload", "document", d.id, filename=d.filename,
              collection_id=collection.id)
    db.commit()
    for d in created:
        document_service.schedule(d.id, strategy=chunking_strategy)
    return UploadResult(documents=[DocumentOut.model_validate(d) for d in created], rejected=rejected)


@router.get("", response_model=DocumentList)
def list_documents(
    collection_id: str | None = None,
    search: str | None = Query(default=None, max_length=200),
    status_filter: str | None = Query(default=None, alias="status", pattern="^(pending|processing|completed|failed)$"),
    file_type: str | None = Query(default=None, max_length=10),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ids = resolve_collection_ids(db, user, [collection_id] if collection_id else None)
    items, total = DocumentRepository(db).list(ids, search=search, status=status_filter, file_type=file_type,
                                               offset=offset, limit=limit)
    return DocumentList(items=[DocumentOut.model_validate(d) for d in items], total=total)


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = readable_document(db, user, document_id)
    out = DocumentDetail.model_validate(d)
    out.logs = [ProcessingLogOut.model_validate(l) for l in d.logs[-200:]]
    out.collection_name = d.collection.name
    return out


@router.get("/{document_id}/logs", response_model=list[ProcessingLogOut])
def get_logs(document_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return readable_document(db, user, document_id).logs


@router.get("/{document_id}/file")
def download_file(document_id: str, request: Request, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    d = readable_document(db, user, document_id)
    data = file_storage.read_bytes(db, d)
    audit(db, request, user, "document.view", "document", d.id)
    db.commit()
    disposition = "inline" if d.file_type in ("pdf", "txt", "md", "markdown", "csv") else "attachment"
    return Response(content=data, media_type=d.mime_type, headers={
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(d.filename)}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.get("/{document_id}/preview", response_model=DocumentPreview)
def preview(document_id: str, page: int | None = Query(default=None, ge=1), user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    d = readable_document(db, user, document_id)
    chunks = ChunkRepository(db).for_page(d.id, page)
    if page is not None and not chunks:
        # chunks spanning several pages start on an earlier page
        chunks = [c for c in ChunkRepository(db).for_page(d.id, None)
                  if c.page_number and c.page_number <= page <= ((c.meta or {}).get("page_end") or c.page_number)]
    return DocumentPreview(document_id=d.id, filename=d.filename, page=page, page_count=d.page_count,
                           chunks=[ChunkOut.model_validate(c) for c in chunks[:500]])


@router.post("/{document_id}/reprocess", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
def reprocess(document_id: str, request: Request, body: ReprocessRequest | None = None,
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    d = writable_document(db, user, document_id)
    body = body or ReprocessRequest()
    if body.chunking_strategy and body.chunking_strategy not in STRATEGIES:
        raise HTTPException(status_code=422, detail=f"chunking_strategy must be one of {STRATEGIES}")
    if body.chunk_size is not None and not (100 <= body.chunk_size <= 8000):
        raise HTTPException(status_code=422, detail="chunk_size must be between 100 and 8000")
    if body.chunk_overlap is not None and not (0 <= body.chunk_overlap < (body.chunk_size or get_settings().chunk_size)):
        raise HTTPException(status_code=422, detail="chunk_overlap must be >= 0 and smaller than chunk_size")
    document_service.reset_for_reprocess(db, d)
    audit(db, request, user, "document.reprocess", "document", d.id, **body.model_dump(exclude_none=True))
    db.commit()
    document_service.schedule(d.id, strategy=body.chunking_strategy, chunk_size=body.chunk_size,
                              chunk_overlap=body.chunk_overlap)
    db.refresh(d)
    return d


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    d = writable_document(db, user, document_id)
    if d.status == "processing" and not document_service.is_stale(d):
        raise HTTPException(status_code=409, detail="Document is being processed; try again shortly")
    name = d.filename
    document_service.delete_document(db, d)
    audit(db, request, user, "document.delete", "document", document_id, filename=name)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
