# Deploying to Vercel

The whole stack runs on Vercel as **two projects from this one repository**:

| Vercel project | Root directory | What it runs |
|---|---|---|
| `rag-api` (any name) | `backend` | FastAPI as a Python function (`api/index.py`) |
| `rag-web` (any name) | `frontend` | Next.js app |

Plus a **Postgres database with the pgvector extension**, e.g. Neon from the Vercel Marketplace. It stores
users, documents, chunks, conversations, the uploaded files and the vectors. Nothing is kept on the
function's disk.

## How the serverless mode differs

The backend detects Vercel (the `VERCEL` environment variable) and switches to serverless mode:

- **Documents are processed inside the upload request**, because background threads don't survive the
  response. The upload therefore returns when the document is ready, or has failed. The UI uploads one file
  per request.
- **Vectors go in pgvector** (`VECTOR_STORE=pgvector`) and **original files in Postgres**
  (`FILE_STORAGE=database`).
- **Size limit: files up to 4 MB.** Vercel caps request bodies at 4.5 MB, so set `MAX_UPLOAD_SIZE_MB=4`.
- **Time limit:** functions may run up to `maxDuration` (300 s in `backend/vercel.json`, the Hobby maximum).
  Small and medium documents fit easily; very long PDFs with semantic chunking may not. On Pro you can raise
  `maxDuration` to 800.
- **Connections:** no connection pool is kept inside the function, and prepared statements are disabled, so
  Neon's pooled (PgBouncer) connection string works.
- **Stalled work:** documents stuck in "processing" (a function that was killed) can be re-processed or
  deleted after 15 minutes. Evaluation runs stuck for an hour are marked failed.
- **Slim install:** the backend installs only `backend/requirements.txt`. Chroma, FAISS and
  `langchain-community` are left out; built-in readers replace the LangChain loaders and give identical
  output (covered by tests).

## Step by step

### 1. Push the repository to GitHub

Vercel deploys from Git. The repository is already on GitHub.

### 2. Create the backend project

1. In Vercel: **Add New… → Project**, then import this repository.
2. **Root Directory:** `backend`. **Framework Preset:** *Other*. Leave the build and output settings empty.
3. Before the first deploy, add a database: open the project's **Storage** tab, then **Create Database →
   Neon (Postgres)**, and connect it to this project. This adds `DATABASE_URL` and related variables. Use the
   pooled URL if you're asked to choose. The app enables pgvector and creates its tables on first use.
4. Under **Settings → Environment Variables**, add the following (template: `backend/.env.vercel.example`):

| Variable | Value |
|---|---|
| `GOOGLE_API_KEY` | your Gemini API key |
| `JWT_SECRET_KEY` | a random string of at least 32 characters, e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ENVIRONMENT` | `production` |
| `VECTOR_STORE` | `pgvector` |
| `FILE_STORAGE` | `database` |
| `MAX_UPLOAD_SIZE_MB` | `4` |
| `CORS_ORIGINS` | the frontend URL, e.g. `https://rag-web.vercel.app` (fill in after step 3) |
| `CORS_ORIGIN_REGEX` | optional, to also allow preview deployments: `^https://rag-web(-[a-z0-9-]+)?\.vercel\.app$` |
| `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` | optional: creates the first admin. Otherwise the first account to register becomes admin, so register right after deploying. |
| `ALLOW_REGISTRATION` | `false` once your users exist, if you don't want open sign-up |

The Gemini model variables (`GEMINI_CHAT_MODEL`, …) are optional; see `backend/.env.example`.

5. Click **Deploy**, then open `https://<backend>.vercel.app/api/health`. It should report
   `"status": "ok"` and `"vector_store": "pgvector"`.

### 3. Create the frontend project

1. **Add New… → Project**, then import the **same** repository again.
2. **Root Directory:** `frontend`. Next.js is detected automatically; `frontend/vercel.json` also pins
   `"framework": "nextjs"`, because a project created without a framework preset (e.g. with
   `vercel project add`) builds fine but serves 404 for every page.
3. Environment variable: `NEXT_PUBLIC_API_URL` = `https://<backend>.vercel.app` (no trailing slash).
4. Click **Deploy**.

### 4. Connect the two

Put the frontend's production URL into the backend's `CORS_ORIGINS` (and `CORS_ORIGIN_REGEX` if you use
previews). Then redeploy the backend: **Deployments → … → Redeploy**. Environment variable changes only apply
to new deployments.

### 5. Check it works

1. Open the frontend and register. The first account becomes the administrator.
2. Go to **Settings → AI models → Verify models**. Each configured Gemini model should show a green check.
   If one is missing, change its `GEMINI_*` variable on the backend and redeploy.
3. Upload a small PDF on **Documents**. It should reach *Ready*. Then ask a question in **AI Assistant** and
   click a citation.

## Good to know

- **Streaming:** answers are streamed with Server-Sent Events. If the platform buffers the response, the
  answer appears all at once when it is complete. Nothing breaks.
- **Cold starts:** the first request after a period of inactivity takes a few extra seconds while Python
  imports the app.
- **Evaluation:** a full run (3 chunking × 3 retrieval strategies with answer generation) makes hundreds of
  Gemini calls and can exceed the 300 s limit. On Vercel, run fewer strategies, untick *Evaluate answers*,
  or run the CLI locally: `python -m app.evaluation.test_pipeline` (see the README).
- **Rate limiting** is counted per function instance, so it is weaker on serverless. For strict limits, add
  Vercel's WAF rate-limiting rules or a Redis-backed limiter.
- **Bundle size:** the slim install is about 290 MB including compiled `.pyc` files (about 200 MB without),
  within Vercel's documented Python function limit. Set `VERCEL_ANALYZE_BUILD_OUTPUT=1` on the backend
  project to see the size in the build log.
- **Changing the embedding model or dimension:** the `rag_vectors` table is created with a fixed dimension.
  Drop it (`DROP TABLE rag_vectors;`) and re-process the documents.
- **Local reproduction of the Vercel setup:** run a pgvector Postgres
  (`docker run -p 5432:5432 -e POSTGRES_PASSWORD=pw pgvector/pgvector:pg17`), install only
  `requirements.txt`, and start the backend with `VERCEL=1 VECTOR_STORE=pgvector FILE_STORAGE=database
  DATABASE_URL=postgres://postgres:pw@localhost:5432/postgres uvicorn api.index:app`.

## Deploying with the CLI instead of the dashboard

```bash
npm i -g vercel
```

```bash
cd backend && vercel link --project <api-project> && vercel integration add neon && vercel deploy --prod
```

```bash
cd frontend && vercel link --project <web-project> && vercel deploy --prod
```

Set the environment variables with `vercel env add <NAME> production` before the first deploy, as listed above.
