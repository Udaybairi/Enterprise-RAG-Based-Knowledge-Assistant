# Response to the engineering audit

This document tracks each finding of the external engineering audit and records one of four outcomes:
**fixed** (with the regression test that proves it), **already in place**, **planned**, or **disagree**
(with the reason). Status is based on code and tests in this repository; nothing here is a claim of
production certification.

## Phase 1 — fixed

| Finding | What changed | Regression test |
|---|---|---|
| First registered user becomes admin (critical) | Off by default when `ENVIRONMENT=production`; it stays on in development and test, and an explicit `FIRST_USER_IS_ADMIN=true` re-enables it. The first admin is provisioned with `BOOTSTRAP_ADMIN_*` or `python -m app.manage create-admin`. | `test_first_user_admin_off_by_default_in_production` |
| Race between simultaneous first registrations | Bootstrap-admin claim is an insert into `app_flags` (primary key), so exactly one transaction can win, across processes and instances. | `test_bootstrap_flag_can_be_claimed_only_once_under_concurrency` (8 threads; also passes on PostgreSQL) |
| Passwords silently truncated to 72 bytes (high) | Passwords over 72 bytes are rejected at registration (by bytes, not characters) and never match at login; `hash_password` refuses them. | `test_passwords_over_72_bytes_are_rejected_not_truncated` |
| Forwarded IP trusted without a proxy boundary | `X-Forwarded-For` is ignored unless `TRUSTED_PROXY_HOPS` > 0; with N hops the N-th entry from the right is used, so client-forged entries are ignored. Applies to rate limiting and audit logs. The Docker image no longer passes `--forwarded-allow-ips=*`. | `test_forwarded_for_is_not_trusted_without_proxy_hops`, `test_forwarded_for_uses_rightmost_trusted_hop` |
| Rate-limiter key map grows without bound | Idle keys are swept periodically. | `test_rate_limiter_drops_idle_keys` |
| SQL / vector-store consistency on re-processing | Worse than reported: stale vectors were deleted **before** the SQL commit. Now: (1) only add vectors, (2) atomically replace chunk rows, (3) only then delete vectors without a committed row. A failed re-process keeps the previous version active (status stays `completed` with an explanatory message). Every store gained `ids_for_document`, and cleanup and deletion reconcile against what the store actually holds, removing orphans from interrupted runs. | `test_failed_reprocess_keeps_previous_version_searchable` (injects a DB failure mid-swap), `test_orphan_vectors_are_reconciled_on_reprocess_and_delete` |
| Citation points at text the model never saw (context truncation) | `ContextSource` keeps the exact (possibly truncated) passage sent to the model; snippets and support checks use it, and citations carry `context_truncated`. | `test_citation_snippet_comes_from_truncated_context` |
| Health check ignores model status; diagnostics are public | `/api/health` is a minimal public probe (`{"status"}`, HTTP 503 when degraded) that round-trips to the database and vector store. Admin-only `/api/health/details` has the full diagnostics and reports `degraded` when the Gemini model check failed. | `test_health`, `test_health_details_admin_only_and_counts_model_failures` |
| Schema created lazily without migrations (found in production) | Deploying this change cold-started the API in two regions at once; both created the new table and one crashed with `UniqueViolation` on `pg_type`. All schema DDL (app tables and the pgvector table) now runs under a PostgreSQL advisory lock. Alembic remains planned. | `test_concurrent_schema_creation_does_not_race` (8 concurrent instances; fails without the lock, passes with it) |
| Interrupted stream leaves an unanswered question | The chat shows a **Retry** action for a trailing unanswered question, which re-answers it without duplicating it. | Browser test: delete the stored answer, reopen the conversation, retry, check message order |
| Fusion score shown as "relevance" | Citation cards show the cosine **similarity**, labelled and explained, instead of the strategy-dependent ranking score. All scores (vector, keyword, rerank) remain separate fields in the API. | Lint and type-check; manual review |
| `lint` was only `tsc --noEmit` | Real ESLint (`eslint-config-next` core-web-vitals and TypeScript rules); type-checking is a separate `npm run typecheck`. Fixing the findings also fixed two real bugs: stale responses overwriting newer ones in `useAsync`, and the document viewer fetching the previous page and racing the correct one. | `npm run lint` in CI |

## Already in place (audit could not verify, or listed as missing)

| Item | Where |
|---|---|
| Containers run as non-root | `backend/Dockerfile` (`USER appuser`) and `frontend/Dockerfile` (`USER app`), verified with `id -un` in running containers. |
| Tests actually run | 100 backend tests pass on SQLite + Chroma, SQLite + FAISS, PostgreSQL, and the Vercel configuration (pgvector + database file storage); CI runs all four. |
| Tenant isolation tests | `test_tenant_isolation`, `test_organization_collection_shared_read_only`. |
| Deletion removes all associated data | `test_delete_document_cleans_vectors`, `test_delete_collection_removes_everything`, `test_database_file_storage_roundtrip`. |
| Re-processing does not duplicate chunks | `test_reprocess_with_other_strategy` (vector count equals chunk count). |

## Planned (not done yet)

Ordered by the audit's own priority. These change deployment architecture or need data, so each needs a
decision rather than a quick patch.

1. **Cookie-based sessions instead of `localStorage` bearer tokens**, with refresh-token rotation and
   revocation. Prerequisite: serve the API same-origin as the frontend (a Next.js rewrite or a custom
   domain). The frontend and API are on two different `*.vercel.app` sites, and `vercel.app` is on the
   Public Suffix List, so browsers treat cookies between them as third-party and increasingly block them.
2. **Alembic migrations** (tables are currently created with `create_all`).
3. **Durable job queue** (Redis + RQ or Celery, with a transactional outbox), retries, dead-letter queue and
   cancellation. This replaces both the in-process thread pool and processing inside the request on Vercel.
   It needs a worker host, which Vercel functions are not.
4. **Redis-backed rate limiting** shared across instances (or edge rate-limit rules on Vercel).
5. **Object storage** for original files (instead of local disk or Postgres `BYTEA`).
6. **Claim-level citation verification**: split the answer into claims and check each cited passage for
   entailment with the utility model, flagging unsupported numbers and dates.
7. **Evaluation**: grow the gold set from 14 to several hundred human-reviewed cases (multi-hop, tables,
   conflicting and temporal evidence, adversarial documents, access control); add nDCG@k and citation
   precision/recall; run a fixed benchmark in CI with regression thresholds. The cases must be written and
   reviewed by people, and real-model runs need an API budget, so this cannot be generated automatically.
8. Account lifecycle: password reset, email verification, optional MFA (mandatory for admins).
9. Observability: OpenTelemetry traces linking upload → ingestion → retrieval, token and cost metrics,
   error tracking.
10. RAG upgrades: parent–child retrieval, cross-encoder reranking, OCR for scanned PDFs, table-aware
    retrieval, document versioning.

## Where this response disagrees

- **"Disable public registration by default."** For a demo that recruiters should be able to try,
  self-registration stays on. The real risk was automatic admin promotion, which is now fixed. Operators
  can set `ALLOW_REGISTRATION=false`; invitation-based sign-up is planned with the account-lifecycle work.
- **Separate vector database.** Agreed with the audit's own conclusion: pgvector is sufficient until
  measured load says otherwise.
