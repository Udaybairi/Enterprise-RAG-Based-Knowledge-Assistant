from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import audit, get_current_user, resolve_collection_ids
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.core.rate_limit import rate_limit
from app.database.models import Conversation, Message, User
from app.database.repositories import ConversationRepository
from app.database.session import get_db, session_scope
from app.rag.chain import RAGChain
from app.rag.guardrails import validate_query
from app.retrieval.retriever import RetrievalConfig
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationSummary,
    FeedbackRequest,
    MessageOut,
)
from app.services.suggestions import suggest_questions

router = APIRouter(prefix="/api/chat", tags=["chat"])
log = get_logger(__name__)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


def _persist_answer(conversation_id: str, final: dict) -> str:
    with session_scope() as db:
        conv = db.get(Conversation, conversation_id)
        meta = {"grounded": final["grounded"], "rewritten_query": final.get("rewritten_query"),
                "latency_ms": final["latency_ms"], "retrieval": final.get("retrieval", {})}
        msg = ConversationRepository(db).add_message(conv, "assistant", final["answer"], final["citations"], meta)
        return msg.id


@router.post("", dependencies=[Depends(rate_limit("chat"))])
def chat(body: ChatRequest, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    question = validate_query(body.message)
    collection_ids = resolve_collection_ids(db, user, body.collection_ids)
    repo = ConversationRepository(db)

    if body.conversation_id:
        conv = repo.get_owned(body.conversation_id, user.id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conv = Conversation(user_id=user.id, title=question[:80], collection_ids=body.collection_ids or [])
        db.add(conv)
        db.flush()

    msgs = list(conv.messages)
    if body.regenerate:
        # drop trailing assistant answers and re-answer the last user question
        while msgs and msgs[-1].role == "assistant":
            db.delete(msgs.pop())
        if not msgs or msgs[-1].role != "user":
            raise HTTPException(status_code=400, detail="Nothing to regenerate")
        question = msgs[-1].content
        history = [(m.role, m.content) for m in msgs[:-1]]
    else:
        history = [(m.role, m.content) for m in msgs]
        repo.add_message(conv, "user", question)
    if body.collection_ids:
        conv.collection_ids = body.collection_ids
    audit(db, request, user, "chat.query", "conversation", conv.id, collections=len(collection_ids))
    db.commit()

    o = body.options
    cfg = RetrievalConfig.from_settings(top_k=o.top_k, similarity_threshold=o.similarity_threshold,
                                        strategy=o.strategy, reranker=o.reranker, document_ids=o.document_ids,
                                        file_types=o.file_types)
    chain = RAGChain()
    kwargs = dict(history=history, cfg=cfg, rewrite=o.use_query_rewriting, multi_query=o.multi_query)
    conv_id = conv.id

    if not body.stream:
        result = chain.run(question, collection_ids, **kwargs)
        final = {"answer": result.answer, "citations": result.citations, "grounded": result.grounded,
                 "rewritten_query": result.rewritten_query, "latency_ms": result.latency_ms,
                 "retrieval": result.retrieval}
        message_id = _persist_answer(conv_id, final)
        return ChatResponse(conversation_id=conv_id, message_id=message_id, **final)

    def events() -> Iterator[str]:
        yield _sse({"type": "meta", "conversation_id": conv_id, "title": conv.title})
        try:
            for ev in chain.stream(question, collection_ids, **kwargs):
                if ev["type"] == "final":
                    ev.pop("contexts", None)
                    ev.pop("context_chunk_ids", None)
                    ev["message_id"] = _persist_answer(conv_id, ev)
                    ev["conversation_id"] = conv_id
                yield _sse(ev)
        except AppError as exc:
            log.warning("chat failed: %s", exc.message)
            yield _sse({"type": "error", "message": exc.message})
        except Exception:  # noqa: BLE001
            log.exception("chat stream failed")
            yield _sse({"type": "error", "message": "An internal error occurred while generating the answer."})
        yield _sse({"type": "done"})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/history", response_model=list[ConversationSummary])
def history(limit: int = Query(default=100, ge=1, le=500), user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    repo = ConversationRepository(db)
    convs = repo.list_for_user(user.id, limit)
    counts = repo.message_counts([c.id for c in convs])
    out = []
    for c in convs:
        s = ConversationSummary.model_validate(c)
        s.message_count = counts.get(c.id, 0)
        out.append(s)
    return out


@router.get("/suggestions", response_model=list[str])
def suggestions(collection_ids: list[str] | None = Query(default=None), user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    return suggest_questions(db, resolve_collection_ids(db, user, collection_ids))


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv = ConversationRepository(db).get_owned(conversation_id, user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    out = ConversationDetail.model_validate(conv)
    out.messages = [MessageOut.model_validate(m) for m in conv.messages]
    out.message_count = len(out.messages)
    return out


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.patch("/{conversation_id}", response_model=ConversationSummary)
def rename(conversation_id: str, body: RenameRequest, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    conv = ConversationRepository(db).get_owned(conversation_id, user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.title = body.title.strip()
    db.commit()
    return ConversationSummary.model_validate(conv)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: str, request: Request, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    conv = ConversationRepository(db).get_owned(conversation_id, user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete(conv)
    audit(db, request, user, "chat.delete", "conversation", conversation_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/messages/{message_id}/feedback", response_model=MessageOut)
def feedback(message_id: str, body: FeedbackRequest, request: Request, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    msg = db.get(Message, message_id)
    if msg is None or msg.conversation.user_id != user.id or msg.role != "assistant":
        raise HTTPException(status_code=404, detail="Message not found")
    msg.feedback = body.rating
    msg.feedback_comment = body.comment
    audit(db, request, user, "chat.feedback", "message", message_id, rating=body.rating)
    db.commit()
    return msg
