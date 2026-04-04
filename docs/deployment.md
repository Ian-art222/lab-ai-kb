# Deployment Guide

## Release Readiness

This repository is ready for test / pre-release deployment with the current scope:

- multi-provider Phase 1 is implemented
- retrieval embedding is fixed to `embedding_*`
- QA query embedding no longer follows `llm_*`
- QA silently skips unindexed, failed, legacy, or incompatible files
- file index metadata records embedding provider / model / dimension

Still required before formal production launch:

- validate real credentials for any provider you plan to use in production
- decide and freeze the retrieval embedding standard
- rebuild uploaded documents under that standard
- rotate `JWT_SECRET_KEY`

## Recommended Default Production-Like Settings

Recommended default combination for test / pre-release:

- Chat:
  - `llm_provider = gemini`
  - `llm_model = gemini-2.5-flash`
- Retrieval embedding:
  - `embedding_provider = qwen`
  - `embedding_model = text-embedding-v4`
  - `embedding_batch_size = 10`

Why:

- Gemini and OpenAI-compatible main flows are already the most verified paths in this repo
- Qwen / DashScope `text-embedding-v4` is a stable retrieval baseline and already has explicit batch protection
- retrieval embedding must remain stable after launch; chat model can be switched independently later

If your environment already depends on a private OpenAI-compatible gateway, a pragmatic alternative is:

- Chat = `openai_compatible`
- Retrieval embedding = `openai_compatible`

but the retrieval embedding model should still be frozen after go-live.

## Environment Variables

### Backend

Backend reads `apps/api/.env`.

Important variables:

- `DATABASE_URL`: PostgreSQL DSN
- `JWT_SECRET_KEY`: required, must be rotated in non-dev environments
- `UPLOAD_DIR`: file storage root, default `uploads`
- `EMBED_BATCH_SIZE`: fallback only, used when system setting `embedding_batch_size` is empty
- `EMBED_RETRY_TIMES`
- `EMBED_RETRY_BASE_DELAY`
- `EMBED_BATCH_DELAY`

Optional provider fallback variables exist in `apps/api/.env.example`, but operationally:

- `llm_*` should be maintained from the system settings page
- `embedding_*` should be maintained from the system settings page
- env values are fallback / bootstrap values, not the long-term operational control plane

### Frontend

Frontend reads `apps/web/.env`.

- leave `VITE_API_BASE_URL` empty in local development to use the built-in Vite proxy
- set `VITE_API_BASE_URL` only when frontend must call a different backend origin directly

Important:

- an old `apps/web/.env` with `VITE_API_BASE_URL=http://127.0.0.1:8000` will override proxy behavior
- after changing frontend env, restart the Vite dev server

## Chat vs Retrieval Embedding

This is the key deployment rule:

- `llm_*` controls answer generation only
- `embedding_*` controls the retrieval space only

Operational guidance:

- you may switch chat model after launch
- do **not** switch `embedding_provider` / `embedding_model` casually after launch
- if retrieval embedding changes, old indexes must be rebuilt

## Database Migration

Current Alembic state should have a single head:

```bash
cd apps/api
.venv\Scripts\alembic heads
```

Apply migrations:

```bash
cd apps/api
.venv\Scripts\alembic upgrade head
```

New environment bootstrap:

1. create PostgreSQL database
2. copy `apps/api/.env.example` to `.env`
3. install backend dependencies
4. run `alembic upgrade head`
5. create admin
6. start backend
7. copy `apps/web/.env.example` to `.env` if needed
8. start frontend

Upgrade existing environment:

1. pull latest code
2. backup database and `UPLOAD_DIR`
3. run `alembic upgrade head`
4. restart backend
5. restart frontend if web assets or env changed

## Startup Commands

### Backend

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\alembic upgrade head
.venv\Scripts\python scripts\create_admin.py admin your-password
.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Frontend

```bash
cd apps/web
npm install
copy .env.example .env
npm run dev -- --host 127.0.0.1 --port 5173
```

## Reindex Preparation

Use the new helper script:

```bash
cd apps/api
.venv\Scripts\python scripts\reindex_files.py --action report
```

It will classify uploaded files into:

- `compatible`
- `needs_index`
- `needs_reindex`
- `legacy_index_missing_metadata`

Rebuild legacy / mismatched indexes:

```bash
cd apps/api
.venv\Scripts\python scripts\reindex_files.py --action reindex-mismatch
```

Rebuild all uploaded files:

```bash
cd apps/api
.venv\Scripts\python scripts\reindex_files.py --action reindex-all
```

Rebuild only selected files:

```bash
cd apps/api
.venv\Scripts\python scripts\reindex_files.py --action reindex-mismatch --file-id 12 --file-id 27
```

Confirm after rebuild:

- settings page `current_index_standard` matches the chosen retrieval standard
- settings page no longer reports `index_standard_mismatch`
- file records move to `indexed`
- QA can answer against the rebuilt files

## Smoke and Acceptance

### Automated smoke

Basic checks:

```bash
cd apps/api
.venv\Scripts\python scripts\smoke_check.py
```

Full flow:

```bash
set LAB_AI_KB_ADMIN_USERNAME=admin
set LAB_AI_KB_ADMIN_PASSWORD=your-password
set LAB_AI_KB_MEMBER_USERNAME=member
set LAB_AI_KB_MEMBER_PASSWORD=your-password
set LAB_AI_KB_RUN_FULL_FLOW=1
.venv\Scripts\python scripts\smoke_check.py
```

Provider connection tests using saved settings:

```bash
set LAB_AI_KB_RUN_PROVIDER_TESTS=1
.venv\Scripts\python scripts\smoke_check.py
```

Current smoke script covers:

- backend reachable
- auth boundaries
- settings read / admin save / status fields
- upload + indexing + QA main flow
- unindexed file is silently skipped when mixed with indexed file
- scope with no compatible indexed files returns the expected concise error

### Manual acceptance checklist

1. open frontend and backend health endpoints
2. log in as admin
3. save settings and confirm echo
4. run LLM test connection
5. run Embedding test connection
6. upload a small file and index it
7. ask a QA question
8. switch only the chat model and repeat QA
9. verify retrieval still works without rebuilding indexes
10. switch retrieval embedding standard only in a test environment, confirm old files require rebuild

## Provider Recommendation

Recommended default for pre-release:

- Chat default: `gemini`
- Retrieval default: `qwen:text-embedding-v4`

Not recommended as default right now:

- `openai`: adapted, but still needs real-credential validation in your target environment
- `anthropic`: chat only, not usable as retrieval embedding default
- `kimi` / `hunyuan`: adapted through aliasing, but not yet the best default choice without live validation
