from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import audit, get_current_user, readable_collection, writable_collection
from app.database.models import Collection, User
from app.database.repositories import CollectionRepository
from app.database.session import get_db
from app.schemas.collection import CollectionCreate, CollectionOut, CollectionUpdate
from app.services.document_service import delete_collection_data

router = APIRouter(prefix="/api/collections", tags=["collections"])


def _out(c: Collection, user: User, stats: dict) -> CollectionOut:
    o = CollectionOut.model_validate(c)
    s = stats.get(c.id, {})
    o.document_count = s.get("document_count", 0)
    o.chunk_count = s.get("chunk_count", 0)
    o.size_bytes = s.get("size_bytes", 0)
    o.can_write = CollectionRepository.can_write(user, c)
    return o


@router.post("", response_model=CollectionOut, status_code=status.HTTP_201_CREATED)
def create_collection(body: CollectionCreate, request: Request, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    repo = CollectionRepository(db)
    if repo.get_by_name(user.id, body.name.strip()):
        raise HTTPException(status_code=409, detail="You already have a collection with this name")
    if body.visibility == "organization" and not user.is_admin:
        raise HTTPException(status_code=403, detail="Only administrators can create organization-wide collections")
    c = repo.create(user.id, body.name.strip(), body.description.strip(), body.visibility)
    audit(db, request, user, "collection.create", "collection", c.id, name=c.name)
    db.commit()
    return _out(c, user, {})


@router.get("", response_model=list[CollectionOut])
def list_collections(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    repo = CollectionRepository(db)
    cols = repo.list_readable(user)
    stats = repo.stats([c.id for c in cols])
    return [_out(c, user, stats) for c in cols]


@router.get("/{collection_id}", response_model=CollectionOut)
def get_collection(collection_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = readable_collection(db, user, collection_id)
    return _out(c, user, CollectionRepository(db).stats([c.id]))


@router.patch("/{collection_id}", response_model=CollectionOut)
def update_collection(collection_id: str, body: CollectionUpdate, request: Request,
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = writable_collection(db, user, collection_id)
    if body.name is not None and body.name.strip().lower() != c.name.lower():
        if CollectionRepository(db).get_by_name(c.owner_id, body.name.strip()):
            raise HTTPException(status_code=409, detail="A collection with this name already exists")
        c.name = body.name.strip()
    if body.description is not None:
        c.description = body.description.strip()
    if body.visibility is not None:
        if body.visibility == "organization" and not user.is_admin:
            raise HTTPException(status_code=403, detail="Only administrators can share collections organization-wide")
        c.visibility = body.visibility
    audit(db, request, user, "collection.update", "collection", c.id)
    db.commit()
    return _out(c, user, CollectionRepository(db).stats([c.id]))


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_collection(collection_id: str, request: Request, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    c = writable_collection(db, user, collection_id)
    if any(d.status == "processing" for d in c.documents):
        raise HTTPException(status_code=409, detail="Wait until documents finish processing before deleting")
    name = c.name
    delete_collection_data(db, c)
    audit(db, request, user, "collection.delete", "collection", collection_id, name=name)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
