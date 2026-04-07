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

## Docker Compose 部署（单机 2 CPU / 4GB）

> 目标：在实验室共享服务器上，以单机单栈方式部署 `web + api + db`，并保持当前架构（LLM/Embedding 继续通过外部 Provider API 调用，本机不做模型推理）。

### 前置条件

- Docker Engine + Docker Compose Plugin（`docker compose` 可用）
- 服务器可访问外部模型 Provider API（如 Gemini / DashScope / OpenAI-compatible）
- 仓库根目录包含：
  - `docker-compose.yml`
  - `apps/api/Dockerfile`
  - `apps/web/Dockerfile`
  - `apps/api/docker/entrypoint.sh`
  - `deploy/nginx.lab-ai-kb.conf`

### 环境变量准备

1. API 环境变量：

```bash
cp apps/api/.env.example apps/api/.env
```

2. 至少修改以下变量：

- `JWT_SECRET_KEY`：改成强随机值
- `LLM_API_KEY` / `EMBEDDING_API_KEY`：填入真实 Provider 密钥
- 其余 `LLM_*` / `EMBEDDING_*` 按你的外部 Provider 调整

3. `DATABASE_URL` 在 Compose 下会由 `docker-compose.yml` 覆盖为容器内地址（`db:5432`），不需要手动改成 `127.0.0.1`。

4. 可选：通过环境变量覆盖 `POSTGRES_PASSWORD`（默认 `postgres`）。

### 首次部署

```bash
docker compose up -d --build
```

说明：

- `api` 容器启动时会自动等待数据库可用，并执行 `alembic upgrade head`
- 之后以单进程 `uvicorn` 启动（无多 worker）
- 默认仅暴露 `web`：`127.0.0.1:8080 -> container:80`

### 更新部署

```bash
git pull
docker compose up -d --build
```

### 数据持久化位置

使用命名卷：

- `db_data`：PostgreSQL 数据目录
- `api_uploads`：后端上传文件目录（容器内 `/app/data/uploads`）
- 以上两类数据在容器重建/更新/重启后都会保留（前提是不删除卷）。
- 备份建议：同时备份 `db_data` 与 `api_uploads`，避免出现“数据库记录存在但文件缺失”。
- ⚠️ 请勿执行 `docker compose down -v`，该命令会删除卷并导致持久化数据丢失。

查看卷：

```bash
docker volume ls
```

### 日志查看

```bash
docker compose logs -f
```

只看某个服务：

```bash
docker compose logs -f api
docker compose logs -f web
docker compose logs -f db
```

### 数据库迁移

常规情况下，`api` 启动会自动执行迁移。也可手工执行：

```bash
docker compose exec api alembic upgrade head
```

### 停止 / 重启

```bash
docker compose stop
docker compose start
```

或完整下线（保留卷）：

```bash
docker compose down
```

### 服务可用性确认

```bash
# 前端首页
curl -I http://127.0.0.1:8080

# API 健康检查（通过前端同源反代）
curl http://127.0.0.1:8080/health

# 直接查看 api 容器健康状态
docker inspect --format='{{.State.Health.Status}}' lab-ai-kb-api
```

### 2 CPU / 4GB 资源预算说明

当前 compose 为每个服务设置了保守上限（合计不超过目标）：

- `web`: `0.20 CPU`, `256MB`
- `api`: `1.00 CPU`, `1536MB`
- `db`: `0.80 CPU`, `1536MB`

总计：`2.00 CPU`, `3328MB`（留出额外缓冲）。

### 架构边界声明

本部署严格保持当前项目边界：

- 仅包含 `web / api / db` 三个常驻服务
- 不引入 Redis、Celery、MinIO、Elasticsearch、OCR、多模态组件
- 不引入本地 LLM / Embedding 推理服务
- LLM 与 embedding 持续通过外部 Provider API 调用
