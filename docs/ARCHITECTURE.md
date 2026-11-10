# Architecture

This document describes the system architecture, how components interact, the database design and the
security model of the Enterprise RAG Knowledge Assistant.

## 1. System overview

```
┌──────────────────────────── Browser ─────────────────────────────┐
│ Next.js 16 / React 19 / Tailwind 4 / Recharts / Lucide           │
│ Dashboard · Chat (SSE streaming) · Documents · Collections ·     │
│ Evaluation · Settings          JWT in Authorization header        │
└───────────────────────────────┬──────────────────────────────────┘
                                │ REST + text/event-stream
┌───────────────────────────────▼──────────────────────────────────┐
│ FastAPI (app/main.py)                                             │
│  middleware: request-id, security headers, CORS, error mapping    │
│  deps: JWT auth · RBAC · per-bucket rate limiting · audit logging │
│  routes: auth · users · collections · documents · chat · search · │
│          dashboard · evaluation · health/settings                 │
├───────────────┬─────────────────────────────┬────────────────────┤
│ Ingestion     │ Retrieval                   │ RAG chain          │
│ (thread pool) │                             │                    │
│ loaders       │ embed query (Gemini)        │ validate query     │
│ preprocessing │ semantic  (vector store)    │ rewrite follow-up  │
│ chunking ×4   │ keyword   (BM25)            │ multi-query expand │
│ dedup         │ hybrid    (weighted RRF)    │ retrieve → rerank  │
│ embed+cache   │ MMR       (diversity)       │ build context      │
│ index         │ threshold · filters · dedup │ Gemini generate    │
│               │ rerank (lexical / LLM)      │ validate citations │
├───────────────┴───────────────┬─────────────┴────────────────────┤
│ Relational DB (PostgreSQL /   │ Vector store abstraction           │
│ SQLite): users, collections,  │  ChromaDB (persistent, default)    │
│ documents, chunks, logs,      │  FAISS (IndexIDMap2 + FlatIP)      │
│ conversations, messages,      │  one namespace per collection      │
│ embedding cache, audit, evals │                                    │
└───────────────────────────────┴────────────────────────────────────┘
                                │
                     Google Gemini API (google-genai SDK)
             generation model · utility model · embedding model
```

## 2. Component interactions

### 2.1 Upload → index

1. `POST /api/documents/upload` (multipart, up to 20 files). Each file is validated: extension allow-list,
   size limit, magic bytes (`%PDF`, OOXML zip members), zip-bomb guard, binary check for text formats.
2. The SHA-256 of the file is compared with the collection's documents; exact duplicates are rejected.
3. The file is stored as `uploads/<collection_id>/<document_id><ext>` (the user-supplied name is never used as a
   path), a `documents` row is created with status `pending`, and the API returns `202 Accepted`.
4. A bounded thread pool (`services/jobs.py`) runs `ingestion/pipeline.py::process_document`:

| Stage | Module | What happens |
|---|---|---|
| extract | `ingestion/loaders.py` | `PyPDFLoader` (per page), python-docx (headings, tables; `Docx2txtLoader` fallback), python-pptx (slide = page, notes, tables), openpyxl (sheets → markdown tables), `CSVLoader` (row groups), `TextLoader` (encoding detection), markdown heading parser. Unstructured is used as a fallback when installed. |
| preprocess | `ingestion/preprocessing.py` | Unicode NFKC, de-hyphenation, whitespace normalisation, running header/footer + page-number removal, heading detection for plain text, section-path propagation, duplicate paragraph removal, empty/scanned/corrupt detection, prompt-injection flagging. |
| chunk | `chunking/*` | `recursive`, `token`, `structure`, `semantic` (see 2.2). |
| dedup | `ingestion/deduplication.py` | exact (normalised hash) and near-duplicate (5-gram shingle Jaccard / containment) chunk removal. |
| embed | `embeddings/*` | text embedded = `Document: <name>\nSection: <path>\n\n<chunk>` (contextual embedding). Content-hash cache prevents re-embedding. Batches of ≤100, client-side RPM limiter, exponential backoff with jitter on 408/429/5xx. |
| index | `vectorstore/*` | upsert into the collection's namespace; vectors of chunks that no longer exist are deleted (incremental re-processing). |
| persist | `database` | chunk rows (text, page, section, token count, flags) replace the old ones; document → `completed`. |

Every stage writes a timed `processing_logs` row, which the UI shows. On failure the document becomes `failed`
with the error message, and vectors written during that run are rolled back. Jobs left `pending/processing`
are re-queued on startup.

### 2.2 Chunking strategies

| Strategy | Behaviour |
|---|---|
| `recursive` | LangChain `RecursiveCharacterTextSplitter` per page (exact page numbers), offsets mapped back to blocks for section metadata. |
| `token` | Same splitter measured in tokens (tiktoken `cl100k_base` when available, calibrated heuristic otherwise). |
| `structure` | Never crosses a heading boundary; headings repeated on continuation chunks; tables/lists kept whole (tables split on rows with the header repeated); tiny *sibling* sections merged and labelled with their shared parent; sentence-aligned overlap. |
| `semantic` | Within each section: whole paragraphs are units (only oversized paragraphs are split into sentences); each unit is embedded with a ±`buffer` window; cosine distance between consecutive windows; boundaries above the document-level percentile (`SEMANTIC_BREAKPOINT_PERCENTILE`); intra-paragraph boundaries penalised; hard max size; tiny tail chunks merged. One batched embedding call per document. |

### 2.3 Question → answer

```
POST /api/chat {message, conversation_id?, collection_ids?, options, stream}
  │ auth → rate limit → resolve collections (∩ readable by user, 404 otherwise)
  │ persist user message, load history
  ▼
RAGChain.stream()
  1 validate query (length, control chars)
  2 rewrite follow-up → standalone question (utility model, JSON) if history exists
  3 multi-query expansion (N alternative phrasings)
  4 Retriever.retrieve(queries, namespaces, cfg)
      per query × per namespace: dense search (+metadata filter) and/or BM25
      keyword-only hits get a real cosine score → uniform similarity threshold
      hybrid: weighted RRF(vector rank, BM25 rank); MMR: diversity selection
      fuse across queries (RRF, original query weighted highest)
      hydrate from DB — re-checks collection authorisation & document status
      context dedup (near-duplicate overlap removal)
      rerank: lexical cross-scorer or Gemini relevance scoring; drop low relevance
  5 no chunks → fixed "not enough information" answer, no LLM call
  6 build context: numbered <source id page section untrusted?> blocks, token budget
  7 Gemini streaming generation with grounding system prompt
  8 citation validation: map [n] → chunk, strip invalid markers, best snippet per citation,
    support score; uncited non-refusal answers are flagged as unverified
  9 secret redaction, persist assistant message (citations + retrieval metadata)
  ▼
SSE events: meta → status* → token* → final{answer, citations, grounded, latency, retrieval} → done
```

Citations carry `document_id`, `document_name`, `page_number` (only for paginated formats: PDF pages and
PPTX slides — never inferred for DOCX/TXT/CSV/XLSX), `section`, `snippet`, and `score`. In the UI a citation opens
the document viewer: the original PDF at `#page=N` alongside the extracted text of that page with the cited
sentences highlighted.

## 3. Database design

```
users ─────────┐1
  id PK         │
  email UNIQUE  │                 ┌─────────────── collections ────────────────┐
  hashed_password (bcrypt)        │ id PK, owner_id FK→users (CASCADE)          │
  role (admin|user), is_active    │ name, description, visibility               │
  created_at, last_login_at       │ (private|organization)                      │
                │                 │ UNIQUE(owner_id, name)                      │
                │*                └───────────────┬────────────────────────────┘
                │                                 │1
                │                                 │*
conversations   │           documents ────────────┘
  id PK         │             id PK, collection_id FK (CASCADE), owner_id FK
  user_id FK ───┘             filename, stored_path, file_type, mime_type, size_bytes
  title                       content_hash (sha256, indexed), status (indexed), error_message
  collection_ids JSON         page_count, chunk_count, chunking_strategy, embedding_model,
  created_at, updated_at      vector_store, metadata JSON, created/updated/processed_at
        │1                          │1                        │1
        │*                          │*                        │*
messages                       chunks                      processing_logs
  id PK                          id PK (sha1(doc|hash|n))    id PK, document_id FK
  conversation_id FK (CASCADE)   document_id FK (CASCADE)    level, stage, message
  role, content                  collection_id (indexed)     duration_ms, created_at
  citations JSON                 chunk_index, text
  metadata JSON                  content_hash, page_number   embedding_cache
  feedback (-1/0/1), comment     section, token_count          (content_hash, model) PK
  created_at                     metadata JSON                 dimension, vector BYTEA

audit_logs: id, user_id, action, resource_type, resource_id, details JSON, ip_address, created_at
evaluation_runs: id, created_by, status, config JSON, results JSON, error_message, created/finished_at
document_files: document_id PK/FK (CASCADE), data BYTEA        (only with FILE_STORAGE=database)
rag_vectors: (namespace, id) PK, embedding vector(dim), metadata JSONB   (only with VECTOR_STORE=pgvector)
```

* Vectors live only in the vector store; chunk text lives in the DB (source of truth for citations, BM25 and
  previews). The chunk id is shared by both, which makes deletion and incremental updates consistent.
* `embedding_cache` is keyed by `(sha256(text), model@dimension)`, so changing the embedding model never mixes
  vectors from different models.
* Tables are created with SQLAlchemy `create_all` on startup. For schema evolution in production, introduce
  Alembic migrations generated from `app/database/models.py`.

## 4. Vector store abstraction

`app/vectorstore/base.py::VectorStore` defines `upsert / delete / delete_namespace / search(where,
include_vectors) / get_vectors / count`. Implementations:

* **ChromaDB** (`chroma_store.py`): `PersistentClient`, one collection `kb_<collection_id>` per knowledge
  collection, cosine space, `$in`/`$and` metadata filters.
* **FAISS** (`faiss_store.py`): `IndexIDMap2(IndexFlatIP)` on L2-normalised vectors (exact cosine), string↔int
  id map + metadata sidecar written atomically, over-fetch for filtered search, `reconstruct` for MMR.

* **pgvector** (`pgvector_store.py`): one `rag_vectors` table in PostgreSQL (namespace column, `vector(dim)`,
  JSONB metadata, HNSW cosine index), with iterative index scans so namespace and metadata filters stay
  complete. Stateless, so it is the store used for serverless deployments (Vercel + Neon).
* **in-memory** (`memory_store.py`): exact numpy search, used for the isolated evaluation index.

Select with `VECTOR_STORE=chroma|faiss|pgvector`. Adding Qdrant etc. means implementing the same six methods.

## 4a. Deployment modes

| | Server / Docker | Serverless (Vercel) |
|---|---|---|
| Ingestion | background thread pool; jobs re-queued on restart | inside the upload request (`maxDuration` 300 s) |
| Vectors | Chroma or FAISS on disk (or pgvector) | pgvector |
| Original files | `DATA_DIR/uploads` | `document_files` table (BYTEA) |
| DB connections | pooled | no pool in the function; PgBouncer-safe (no prepared statements) |
| Startup | ASGI lifespan | lazy initialisation on first DB use (also covers runtimes without lifespan events) |
| Keyword index | per-process BM25 cache | same, validated against a DB fingerprint so instances never serve stale results |

See [DEPLOY_VERCEL.md](DEPLOY_VERCEL.md).

## 5. Security model

| Concern | Control |
|---|---|
| Authentication | bcrypt password hashes, HS256 JWT access tokens with expiry; production refuses to start with the default/short secret. |
| Authorization | Roles `admin`/`user`. Collections are `private` (owner + admins) or `organization` (everyone may read, only owner/admin may write; only admins may share). Every collection/document lookup goes through `api/deps.py`; unauthorised resources return **404** so IDs are not disclosed. |
| Cross-user leakage | Retrieval only queries namespaces of collections the caller can read (explicit requests for others → 404), and the hydration step re-checks `chunk.collection_id ∈ allowed`. Covered by `test_tenant_isolation`. |
| Prompt injection | Documents are wrapped in `<source>` delimiters; delimiter look-alikes inside documents are neutralised; instruction-like passages are flagged at ingestion and marked `untrusted="true"` in the prompt; the system prompt states sources are data, never instructions. User questions are also neutralised. |
| Hallucination | Answers only from sources; fixed refusal when retrieval is empty; invalid citation markers stripped; uncited answers flagged; never fabricated page numbers. |
| Sensitive data | API keys only in env vars, never returned by the API; model output is scanned for API keys/tokens/private keys and redacted; file downloads `Cache-Control: no-store`. |
| Input validation | Pydantic schemas on every endpoint; upload validation (type, size, magic bytes, zip bomb); safe stored filenames; path-containment check on download. |
| Abuse | Sliding-window rate limits per user/IP for auth, upload, chat/search and default buckets (in-process; swap for Redis when scaling horizontally). |
| Audit | Registrations, logins (incl. failures), uploads, views, deletions, re-processing, chat queries, feedback, role changes and evaluation runs are recorded with user and IP. |
| Transport/headers | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, request ids; CORS restricted to configured origins. |

## 6. Evaluation

`app/evaluation/test_pipeline.py` ingests a gold corpus into an isolated in-memory vector index once per chunking
strategy and runs every retrieval strategy over `data/dataset.json` (question, reference answer, source
documents, evidence spans, including unanswerable questions). Metrics (`metrics.py`): precision@k, recall@k
(evidence coverage), hit rate, MRR, context relevance, answer relevance, faithfulness (Gemini-as-judge with a
lexical fallback), citation accuracy, answer token-F1, hallucination rate (unsupported answers or answering an
unanswerable question), refusal accuracy, and latency. Results are stored in `evaluation_runs` and visualised on
the Evaluation page; the CLI prints a comparison table.
