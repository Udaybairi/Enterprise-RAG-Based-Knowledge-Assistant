# Data governance

What data the assistant stores, where it goes, how long it is kept and how it is deleted. This
describes the code in this repository and the reference deployment (Vercel + Neon + Google Gemini).
It is not legal advice; check the current terms of each provider before processing regulated data.

## Scope

One organisation, multiple users. Each user's private collections are isolated from other users
(enforced on every request and tested). Administrators can read everything. There is **no
tenant/organisation entity**: it is not a multi-tenant SaaS for several customer companies.

## What is stored where

| Data | Where | Notes |
|---|---|---|
| Accounts (email, name, bcrypt password hash, role) | PostgreSQL | Passwords are never stored or logged in plain text |
| Original uploaded files | PostgreSQL (`document_files`, serverless) or local disk (`DATA_DIR/uploads`) | Up to 4 MB per file on Vercel, 50 MB elsewhere |
| Extracted text chunks, page/section metadata | PostgreSQL (`chunks`) | Needed for citations and full-text search |
| Embedding vectors | pgvector (`rag_vectors`) or Chroma/FAISS on disk | Derived from chunk text |
| Embedding cache | PostgreSQL (`embedding_cache`) | Keyed by a hash of the text; stores vectors only, not text |
| Conversations and answers, with provenance (models, prompt version, tokens) | PostgreSQL | Retention window applies (below) |
| Audit log (logins, uploads, deletions, queries, role changes, IP address) | PostgreSQL | Retention window applies (below) |
| Application logs | Vercel runtime logs | Request paths, status codes and timings; no document text or answers. Vercel retains them according to its plan. |

## What is sent to Google Gemini

| When | What is sent |
|---|---|
| Document processing | The text of every chunk, prefixed with the file name and section title (to compute embeddings). Semantic chunking also sends sentence windows. |
| Each question | The question (for its embedding); then the question, the retrieved passages (up to the context budget) and up to 4 recent conversation turns (to generate the answer). Query rewriting sends the question and up to 6 recent turns; expansion sends the question; the optional LLM reranker sends the question and passages (all to the utility model). |
| Settings → Verify models | A request to list available models (no user data). |

Original files are **not** sent; only extracted text is.

**Free tier vs paid tier.** Under Google's Gemini API Additional Terms at the time of writing, content
sent to *unpaid* services may be used by Google to improve its products and may be read by human
reviewers. Content sent to *paid* services is not used that way. The reference deployment uses a
free-tier key. **Do not upload confidential or personal data to a deployment that uses a free-tier
key.** Use a paid (billing-enabled) key and check the current terms at
https://ai.google.dev/gemini-api/terms before doing so. The upload screen shows this notice.

## Retention

| Data | Default | Setting |
|---|---|---|
| Audit logs | 365 days | `AUDIT_LOG_RETENTION_DAYS` (0 = keep forever) |
| Conversations (with all their messages) | 180 days after the last activity | `CONVERSATION_RETENTION_DAYS` (0 = keep forever) |
| Documents, chunks, vectors | until deleted by a user or admin | — |

Retention runs daily via Vercel Cron (`/api/cron/retention`, authenticated with `CRON_SECRET`), and
administrators can run it manually with `POST /api/admin/retention/run`. Each run writes an audit
record with the number of deleted items. Without `CRON_SECRET` (e.g. Docker), schedule the admin
endpoint externally or run it manually.

## Deletion

| Action | What is removed (tested) |
|---|---|
| Delete a document | File bytes, chunk rows, every vector held for the document (including orphans from interrupted runs), keyword index entries |
| Delete a collection | All of its documents as above, plus its vector namespace |
| Delete a conversation | The conversation and all its messages |
| Retention run | Expired audit logs and conversations |

Embedding-cache entries are content-addressed vectors without text, and are shared between identical
chunks, so they are not deleted with a document. Database backups (Neon point-in-time restore,
depending on the plan) can retain deleted data until they expire.

## Known gaps

- No self-service account deletion or data export yet (an admin can deactivate accounts).
- No automatic detection or redaction of personal data in uploaded documents (model output is scanned
  only for credentials such as API keys).
- Data residency depends on where the Neon project and the Vercel functions run; check both
  dashboards.
- Rate limiting and the audit log are not designed for formal compliance regimes (e.g. immutable audit
  storage).
