# Enterprise RAG Knowledge Assistant

A document intelligence platform for organisations. Upload internal documents, then ask questions and get
answers grounded in those documents, with clickable citations to the exact document, page, section and passage.

Built with **FastAPI · LangChain · Google Gemini · ChromaDB / FAISS · PostgreSQL · Next.js 16 · Tailwind 4 · Recharts**.

![Chat with citations (dark mode)](docs/screenshots/chat-dark.png)

| Citation viewer (cited passage highlighted) | Dashboard |
|---|---|
| ![](docs/screenshots/citation-viewer.png) | ![](docs/screenshots/dashboard.png) |
| **Strategy evaluation** | **Document management** |
| ![](docs/screenshots/evaluation.png) | ![](docs/screenshots/documents.png) |

> Screenshots were captured with the offline `fake` provider described below. The answers in them come from
> its extractive test model, not from Gemini.

## Features

- **Ingestion** for PDF, DOCX, PPTX, XLSX, CSV, TXT and Markdown, using LangChain loaders (`PyPDFLoader`,
  `Docx2txtLoader`, `TextLoader`, `CSVLoader`, Unstructured fallback) plus native readers that keep
  headings, tables and slide numbers. Upload validation checks type, size and magic bytes. Duplicate files are
  rejected. Processing runs in the background with per-stage logs.
- **Preprocessing**: Unicode and whitespace normalisation, de-hyphenation, removal of repeated headers, footers
  and page numbers, heading detection, section hierarchy, duplicate-paragraph removal, detection of empty or
  corrupted files, and flagging of prompt-injection text.
- **Four chunking strategies** with configurable size and overlap:
  - recursive character splitting
  - token-based splitting
  - **structure-aware** (respects headings, keeps tables whole)
  - **semantic** (embedding-similarity breakpoints that never split normal paragraphs)
- **Gemini embeddings**:
  - batched requests with client-side rate limiting and exponential-backoff retries
  - task-type aware (separate document and query embeddings), with configurable dimensionality
  - content-hash **embedding cache**, so identical text is never embedded twice
  - incremental re-processing
- **Vector stores**: ChromaDB (persistent), FAISS and **PostgreSQL pgvector** behind one abstraction, with one
  isolated namespace per collection.
- **Retrieval**:
  - semantic, BM25 keyword, **hybrid** (weighted reciprocal-rank fusion) and **MMR** search
  - metadata filters (documents, file types), top-k and a similarity threshold
  - multi-query retrieval and context de-duplication
  - **reranking**: a lexical cross-scorer, or Gemini scoring each passage
- **Advanced RAG**:
  - query validation, conversational **query rewriting**, query expansion
  - context building within a token budget, streaming Gemini generation
  - an explicit "not enough information" answer when retrieval finds nothing
- **Citations**: every factual sentence cites `[n]`. Markers pointing to sources that don't exist are removed.
  Each citation card shows the document, the page (only for real pages), the section, a snippet and a
  relevance score. Clicking one opens the PDF at that page next to the extracted text, with the cited passage
  highlighted.
- **Chat UI**:
  - streaming answers (SSE), with a stop button
  - conversation history, new chat, delete
  - suggested questions, copy, regenerate, thumbs up/down feedback
  - per-question retrieval settings and collection selection
- **Dashboard**: document, processing, failure and chunk counts, collections, storage, embedding status,
  14-day processing activity, file types and recent uploads.
- **Document management**: upload (drag and drop), preview, search and filter, re-process with another
  strategy, delete (vectors are removed too), metadata and processing logs.
- **Security**:
  - JWT authentication with bcrypt-hashed passwords
  - admin and user roles; private or organisation-wide collections
  - document-level access checks and tenant isolation (tested)
  - rate limiting, audit logs and secret redaction
  - uploaded documents are treated as untrusted data in prompts
- **Evaluation**: a gold dataset of question, answer and source triples, plus unanswerable questions.
  - Metrics: precision@k, recall@k, MRR, context relevance, answer relevance, faithfulness (LLM-as-judge),
    citation accuracy, answer F1, hallucination rate, refusal accuracy and latency.
  - Compares chunking × retrieval strategies, with a UI dashboard and a CLI.

**Deploying to Vercel?** Follow **[docs/DEPLOY_VERCEL.md](docs/DEPLOY_VERCEL.md)** (frontend + serverless backend
+ Neon Postgres with pgvector).

See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for the architecture, component interactions, database
schema and security model.

## Quick start (local development)

Prerequisites: Python 3.11+ (developed and tested on 3.13), Node.js 20+ (tested on 22) and a
[Gemini API key](https://aistudio.google.com/apikey).

### 1. Backend

```bash
cd backend
```

```bash
python -m venv .venv && source .venv/bin/activate
```

```bash
pip install -r requirements-dev.txt
```

(`requirements.txt` is the slim set used on Vercel; `requirements-local.txt` adds ChromaDB, FAISS and the
LangChain community loaders; `requirements-dev.txt` adds the test tools.)

```bash
cp .env.example .env
```

Edit `backend/.env` and set at least `GOOGLE_API_KEY` and `JWT_SECRET_KEY`. You can generate a secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

```bash
uvicorn app.main:app --reload --port 8000
```

The API docs are at http://localhost:8000/api/docs. By default the backend uses a SQLite file and ChromaDB under
`backend/data/`. Set `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db` to use PostgreSQL.

**No API key yet?** Start with `LLM_PROVIDER=fake` (and `SIMILARITY_THRESHOLD=0.15`). This uses a
deterministic offline embedder (feature hashing) and an extractive answerer, so every feature can be clicked
through without network access. Answer quality is far below Gemini; it exists for tests and demos.

### 2. Frontend

```bash
cd frontend
```

```bash
npm install
```

```bash
cp .env.example .env.local
```

```bash
npm run dev
```

Open http://localhost:3000 and register. **The first account becomes the administrator.** Upload documents on
the *Documents* page, wait for the *Ready* status, then ask questions in *AI Assistant*.

## Docker (PostgreSQL + backend + frontend)

```bash
cp .env.example .env
```

Edit `.env` and set `GOOGLE_API_KEY`, `JWT_SECRET_KEY` and `POSTGRES_PASSWORD`. Then:

```bash
docker compose up --build
```

The frontend runs at http://localhost:3000 and the API at http://localhost:8000. Data is kept in the `pgdata`
(PostgreSQL) and `ragdata` (uploads and vectors) volumes.

## Configuration

All settings are environment variables. `backend/.env.example` lists every option with comments. The
important ones:

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini`, or `fake` (offline, deterministic) |
| `GOOGLE_API_KEY` | (none) | Gemini API key. It is never exposed by the API. |
| `GEMINI_CHAT_MODEL` | `gemini-flash-latest` | Answer generation model |
| `GEMINI_UTILITY_MODEL` | `gemini-flash-lite-latest` | Query rewriting, expansion, LLM reranking, judging |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding model (`gemini-embedding-2` is also supported) |
| `EMBEDDING_DIMENSION` | `768` | Output dimensionality (Matryoshka truncation) |
| `VECTOR_STORE` | `chroma` | `chroma`, `faiss` or `pgvector` |
| `FILE_STORAGE` | `local` | `local` (disk) or `database` (Postgres; for serverless) |
| `CHUNKING_STRATEGY` | `structure` | `recursive`, `token`, `semantic`, `structure` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1000` / `150` | In characters |
| `RETRIEVAL_STRATEGY` | `hybrid` | `semantic`, `hybrid`, `mmr`, `keyword` |
| `RETRIEVAL_TOP_K` | `6` | Chunks passed to the model |
| `SIMILARITY_THRESHOLD` | `0.45` | Minimum cosine similarity. Tune it on the Evaluation page. |
| `RERANKER` | `lexical` | `none`, `lexical`, `llm` |
| `DATABASE_URL` | SQLite file | PostgreSQL recommended in production |

**Model availability.** Google renames and retires Gemini models regularly. I could not check Google's live
model list while building this (the docs site was not reachable from the build environment), so the defaults
use the `-latest` aliases where Google offers them. On startup the backend calls the Gemini `models.list` API,
checks that each configured model exists and supports the required action, and logs the result. The result is
also shown under *Settings → AI models*, which has a **Verify models** button. If a model is missing, change the
corresponding `GEMINI_*` variable. Changing the embedding model or dimension needs a re-process of existing
documents.

## API

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login` | Create account or sign in (returns a JWT) |
| GET | `/api/auth/me` | Current user |
| GET / PATCH | `/api/users`, `/api/users/{id}/role`, `/api/users/{id}/active` | User administration (admin) |
| POST / GET | `/api/collections` | Create / list readable collections |
| GET / PATCH / DELETE | `/api/collections/{id}` | Read / update / delete a collection, including its vectors and files |
| POST | `/api/documents/upload` | Multipart upload (`files`, `collection_id`, `chunking_strategy`); returns 202 |
| GET | `/api/documents` | List with `collection_id`, `search`, `status`, `file_type`, paging |
| GET / DELETE | `/api/documents/{id}` | Details with processing logs / delete (vectors removed) |
| POST | `/api/documents/{id}/reprocess` | Re-chunk and re-index (strategy, size, overlap) |
| GET | `/api/documents/{id}/file`, `/preview?page=` | Original file / extracted chunks per page |
| POST | `/api/chat` | Ask a question. `stream: true` returns Server-Sent Events, otherwise JSON. |
| GET | `/api/chat/history`, `/api/chat/{id}` | Conversations / one conversation with messages |
| PATCH / DELETE | `/api/chat/{id}` | Rename / delete a conversation |
| POST | `/api/chat/messages/{id}/feedback` | Rate an answer (-1, 0, 1) |
| GET | `/api/chat/suggestions` | Suggested questions |
| POST | `/api/search` | Retrieval only (no generation) |
| GET | `/api/dashboard/stats`, `/api/audit-logs` | Dashboard metrics / audit log (admin) |
| POST / GET | `/api/evaluation/run`, `/api/evaluation/runs[/{id}]`, `/api/evaluation/dataset` | Evaluation |
| GET | `/api/health`, `/api/settings`; POST `/api/settings/check-models` | Health, effective config, model verification |

Streaming chat events: `meta` → `status`* → `token`* → `final` (answer, citations, grounded, latency, retrieval
details) → `done`, or `error`.

## Evaluation

From the UI (admin): open *Evaluation*, pick strategies and click **Run evaluation**. From the CLI:

```bash
cd backend && python -m app.evaluation.test_pipeline --chunking recursive structure semantic --retrieval semantic hybrid mmr
```

Add `--no-generation` to measure retrieval only (much cheaper), and `--output results.json` to save the full
per-question report. Replace `app/evaluation/data/corpus/` and `dataset.json` with your own documents and
question → answer → evidence triples to tune the system on your own content.

## Testing

```bash
cd backend && pytest -q
```

```bash
cd backend && TEST_VECTOR_STORE=faiss pytest -q
```

```bash
cd backend && TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/test pytest -q
```

To test the Vercel configuration (pgvector, files in Postgres, serverless mode), point the tests at a database
with the pgvector extension:

```bash
cd backend && VERCEL=1 FILE_STORAGE=database TEST_VECTOR_STORE=pgvector TEST_DATABASE_URL=postgres://user:pass@localhost:5432/test TEST_PGVECTOR_URL=postgresql+psycopg://user:pass@localhost:5432/test pytest -q
```

```bash
cd frontend && npm run lint && npm run build
```

The 88 backend tests run offline with the deterministic provider. They cover:

- loaders for every format, preprocessing, and all four chunkers
- all vector stores (Chroma, FAISS, pgvector, in-memory), MMR/RRF and the rerankers
- citation validation, guardrails, embedding cache, retries and Gemini request batching (mocked client)
- the full HTTP API: auth, RBAC, **tenant isolation**, ingestion, search with every strategy, streaming chat,
  follow-ups, regeneration, refusals, re-processing without stale vectors, deletion cleanup, audit logs
- the evaluation harness

CI (`.github/workflows/ci.yml`) runs the suite on SQLite + Chroma, SQLite + FAISS, PostgreSQL, and the Vercel
configuration (slim install + pgvector + files in Postgres), and builds the frontend.

## Deployment notes

**Vercel:** see [docs/DEPLOY_VERCEL.md](docs/DEPLOY_VERCEL.md). **Docker / VM / container platforms:** use
`docker-compose.yml` or the two Dockerfiles. General notes:

- Set `ENVIRONMENT=production`. The API then refuses to start without a strong `JWT_SECRET_KEY`.
- Use PostgreSQL, and put the API behind TLS: a reverse proxy (`--proxy-headers` is enabled) or a managed load
  balancer.
- Set `CORS_ORIGINS` to the frontend origin, and build the frontend with `NEXT_PUBLIC_API_URL` set to the public
  API URL.
- Keep `/data` (uploads and vector indexes) on a persistent volume and back it up together with the database.
- **Scaling.** Ingestion runs in an in-process thread pool, and rate limiting and the BM25 cache are also
  in-process. That is fine for a single API replica. For several replicas:
  - move ingestion to a task queue (Celery/RQ/Cloud Tasks calling `process_document`)
  - back rate limiting with Redis
  - run Chroma in client/server mode, or implement the `VectorStore` interface for a managed vector database
- Schema changes: tables are created automatically. Add Alembic migrations before changing models in
  production.

## Project structure

```
backend/app
├── main.py, config.py
├── api/            deps.py (auth, RBAC, access checks), routes/ (auth, collections, documents, chat, search,
│                   dashboard, evaluation, health)
├── core/           security (JWT, bcrypt), logging, rate_limit, exceptions
├── ingestion/      loaders, validation, preprocessing, deduplication, pipeline
├── chunking/       recursive, token, structure, semantic chunkers + factory
├── embeddings/     gemini_embeddings, fake_embeddings, cache, factory
├── vectorstore/    base abstraction, faiss_store, chroma_store, pgvector_store, memory_store
├── retrieval/      semantic_search (+MMR), hybrid_search (RRF), keyword_index (BM25), reranker, retriever
├── rag/            prompts, guardrails, query_rewriter, context_builder, generator, citation_manager, chain
├── llm/            Gemini client, offline client, retry/rate limiting
├── evaluation/     metrics, test_pipeline (strategy comparison), data/ (corpus + gold dataset)
├── database/       models, repositories, session
├── schemas/        Pydantic request/response models
└── services/       document lifecycle, file storage, background jobs, model check, suggestions
backend/api/index.py, backend/vercel.json   Vercel entrypoint and function config
frontend/
├── app/            (auth)/login, register · (app)/ dashboard, chat, documents, collections, evaluation, settings
├── components/     AppShell, ChatMessage + citation cards, DocumentViewer, UploadDropzone, ui primitives
├── hooks/          useAuth, useTheme, useAsync
├── services/       api.ts (REST + SSE client)
└── types/
```

## Known limitations

- Scanned (image-only) PDFs are reported as "no extractable text"; OCR is not included.
- DOCX, TXT, CSV and XLSX have no fixed pages, so their citations show the section or row range instead of a
  page number. Page numbers are never guessed.
- Inline highlighting happens in the extracted-text pane. The original PDF opens at the cited page in the
  browser's PDF viewer, which does not support programmatic highlighting.
- `langchain-community` is being sunset upstream. Its loaders are pinned here, and every LangChain loader used
  has a native fallback or replacement in `ingestion/loaders.py`.
