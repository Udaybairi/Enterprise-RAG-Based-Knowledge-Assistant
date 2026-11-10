from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, resolve_collection_ids
from app.config import get_settings
from app.core.rate_limit import rate_limit
from app.database.models import User
from app.database.session import get_db
from app.llm.factory import get_llm
from app.rag.query_rewriter import QueryRewriter
from app.retrieval.retriever import RetrievalConfig, Retriever
from app.schemas.chat import SearchHit, SearchRequest, SearchResponse

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("", response_model=SearchResponse, dependencies=[Depends(rate_limit("chat"))])
def search(body: SearchRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t0 = time.perf_counter()
    collection_ids = resolve_collection_ids(db, user, body.collection_ids)
    o = body.options
    cfg = RetrievalConfig.from_settings(top_k=o.top_k, similarity_threshold=o.similarity_threshold,
                                        strategy=o.strategy, reranker=o.reranker, document_ids=o.document_ids,
                                        file_types=o.file_types)
    multi = o.multi_query if o.multi_query is not None else False
    plan = QueryRewriter(get_llm()).plan(body.query, [], rewrite=False, expand=multi,
                                         n_expansions=get_settings().multi_query_count)
    chunks = Retriever().retrieve(plan.queries, collection_ids, cfg, rerank_query=plan.standalone)
    hits = [SearchHit(chunk_id=c.chunk_id, document_id=c.document_id, document_name=c.filename,
                      collection_id=c.collection_id, page_number=c.page_number, section=c.section, text=c.text,
                      score=round(c.score, 4), vector_score=c.vector_score, keyword_score=c.keyword_score)
            for c in chunks]
    return SearchResponse(query=body.query, queries=plan.queries, hits=hits,
                          latency_ms=round((time.perf_counter() - t0) * 1000, 1))
