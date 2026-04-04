# Troubleshooting Guide

## Startup Failures

### Backend cannot start

Check:

- `apps/api/.env` exists
- `DATABASE_URL` is correct
- PostgreSQL is reachable
- migrations are applied

Commands:

```bash
cd apps/api
.venv\Scripts\alembic current
.venv\Scripts\alembic upgrade head
.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Frontend cannot access API

Check:

- backend is running on `127.0.0.1:8000`
- `apps/web/.env` is not forcing a stale `VITE_API_BASE_URL`
- if using local dev, leave `VITE_API_BASE_URL=` empty to use the Vite proxy

## Migration Problems

### `alembic upgrade head` fails

Check:

- you are using the project virtualenv executable
- the database user has schema migration permissions
- `alembic heads` returns a single head

Commands:

```bash
cd apps/api
.venv\Scripts\alembic heads
.venv\Scripts\alembic history --indicate-current
```

Expected current head in this repo:

- `a1b2c3d4e5f6`

## Failed to Fetch / Proxy / CORS / API Base

Typical causes:

- backend not running
- frontend `.env` still points to an old API origin
- browser calls a direct backend origin instead of the Vite proxy
- mixed hostnames (`localhost` vs `127.0.0.1`)

Current intended local behavior:

- frontend calls relative `/api/...`
- Vite proxy forwards `/api` to `http://127.0.0.1:8000`

What to check:

1. open `http://127.0.0.1:8000/docs`
2. open `http://127.0.0.1:5173/`
3. inspect browser Network tab and confirm the real request URL
4. if `VITE_API_BASE_URL` is set, confirm it is intentional

## Provider Authentication Failures

### `AUTH_ERROR`

Check:

- API key
- organization / project fields if applicable
- provider-native key type is correct
- saved settings are actually the intended environment values

### `NOT_FOUND`

Check:

- model name
- base URL
- provider/model pairing

### `RATE_LIMIT` / quota errors

Check:

- provider quota
- request concurrency
- embedding batch size

For Qwen / DashScope:

- keep `embedding_batch_size <= 10`

## Retrieval Embedding Standard Issues

### Why can chat model change but embedding model should not?

Because:

- chat model only generates the final answer from retrieved context
- embedding model defines the vector space for indexing and retrieval

Changing chat model:

- safe, no reindex required

Changing retrieval embedding provider/model:

- old indexes may become incompatible
- rebuild is required

### Why does QA skip some files?

This is now expected behavior.

QA silently skips files that are:

- not indexed
- indexing failed
- indexed with a different retrieval embedding standard
- legacy indexed without index metadata
- indexed with a different embedding dimension

This prevents one bad or old file from blocking the whole scope.

### When will QA still return an error?

Only when the current scope has no compatible indexed files for the current retrieval standard.

Expected error:

- `当前范围内没有可用于当前知识库索引标准的已索引文献，请先建立或重建索引。`

## Reindex / Index Standard Mismatch

Check current index situation:

```bash
cd apps/api
.venv\Scripts\python scripts\reindex_files.py --action report
```

Rebuild mismatched or legacy indexes:

```bash
.venv\Scripts\python scripts\reindex_files.py --action reindex-mismatch
```

If you intentionally changed the retrieval standard:

1. save new `embedding_provider` / `embedding_model`
2. run reindex report
3. rebuild mismatched files
4. verify settings page no longer shows mismatch

## Upload Directory / File Storage

Current file storage root is controlled by:

- `UPLOAD_DIR`

Default:

- `uploads`

Check:

- process has write permission
- storage path exists or can be created
- deployment backups include this directory

## Recommended First Response Checklist

When something breaks in a pre-release environment:

1. check backend health and `/docs`
2. check `alembic current`
3. check settings page provider and retrieval standard
4. run `scripts\reindex_files.py --action report`
5. run `scripts\smoke_check.py`
6. inspect backend logs for provider errors, DB errors, or path issues
