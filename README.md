# Lab AI KB

Lab AI KB 是一个私有化文本知识库系统（FastAPI + PostgreSQL/pgvector + Vue 3），提供文件管理、索引、RAG 问答与管理员诊断能力。

> 本 README 已按 **2026-04-07 仓库代码与本轮审查结果**更新，重点强调“已验证项 / 未验证项”。

---

## 1. 当前能力（按代码现状）

- 认证与权限：JWT 登录；用户角色区分 `admin/member`；管理员诊断接口强制 `admin` 才可访问。
- 文件中心：目录树、上传、下载、删除、移动、详情。
- 索引链路：单文件建索引、重建索引（force reindex）、索引状态查询。
- QA 主链路：`POST /api/qa/ask`，支持 scope（all/folder/files）、strict/non-strict、引用返回。
- Agent/RAG 元信息：`task_type`、`selected_skill`、`selected_scope`、`planner_meta`、`compare_result`、`clarification_needed`、`workflow_summary` 等字段。
- diagnostics：trace 列表、详情、导出、reason stats、retry-index。
- 评测脚本：`scripts/eval_rag.py`（对比 rerank off/on）。

---

## 2. 项目结构

```text
apps/
  api/                 # FastAPI + SQLAlchemy + Alembic
  web/                 # Vue3 + Vite + Element Plus
docs/                  # 部署、排障、阶段文档
evals/                 # eval 数据与报告
docker-compose.yml     # 最小可运行栈（db + api + web）
```

---

## 3. 开发环境要求

- Python 3.10+
- Node.js 20+（建议 22）
- PostgreSQL 16 + pgvector（本地或 Docker）

---

## 4. 本地开发启动（推荐）

### 4.1 API

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate  # Windows 用 .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # Windows 用 copy

# 确保 DATABASE_URL 指向可用 PostgreSQL（需 pgvector）
alembic upgrade head

# 创建管理员
python scripts/create_admin.py admin 'your-password'

# 启动 API
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 4.2 Web

```bash
cd apps/web
npm install
cp .env.example .env
npm run dev -- --host 127.0.0.1 --port 5173
```

默认开发代理：`/api -> http://127.0.0.1:8000`。

---

## 5. Docker Compose 启动

### 5.1 首次准备

```bash
cp .env.example .env
cp apps/api/.env.example apps/api/.env
```

> `apps/api/.env` 中的 `DATABASE_URL` 会被 compose 的 `api.environment.DATABASE_URL` 覆盖为容器内地址（`db:5432`）。

### 5.2 启动

```bash
docker compose up -d --build
```

**仅更新前端 UI 时**：不要只执行 `docker compose build web`，否则运行中的容器仍挂载旧镜像里的静态文件。应重建并替换容器，任选其一：

```bash
./scripts/docker-rebuild-web.sh
```

或：

```bash
docker compose up -d --build --force-recreate web
```

服务默认端口：
- Web: `http://127.0.0.1:8080`
- API: `http://127.0.0.1:8000`
- DB: `127.0.0.1:5432`

### 5.3 健康检查

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8080/health
```

---

## 6. 数据库迁移（Alembic）

```bash
cd apps/api
alembic upgrade head
alembic current
```

---

## 7. 创建管理员

```bash
cd apps/api
python scripts/create_admin.py <username> '<password>'
```

---

## 8. 测试与检查

### 8.1 后端测试

```bash
cd apps/api
pytest -q
```

### 8.2 前端类型检查

```bash
cd apps/web
npm run type-check
```

### 8.3 前端单测

```bash
cd apps/web
npm run test:unit
```

---

## 9. smoke / acceptance

### 9.1 基础 smoke

```bash
cd apps/api
python scripts/smoke_check.py
```

### 9.2 管理员 diagnostics smoke

```bash
cd apps/api
python scripts/smoke_phase25_admin_diagnostics.py \
  --base-url http://127.0.0.1:8000 \
  --admin-user <admin> \
  --admin-pass <admin_pass> \
  --member-user <member> \
  --member-pass <member_pass>
```

---

## 10. 运行 evals

```bash
cd apps/api
python scripts/eval_rag.py \
  --input evals/source_diversity_eval.sample.jsonl \
  --output /tmp/eval_report.json
```

说明：样例集通常只验证链路，不代表真实线上效果。

---

## 11. diagnostics / 管理员能力

前端页面：`/admin/diagnostics`

后端接口：
- `GET /api/admin/diagnostics/traces`
- `GET /api/admin/diagnostics/traces/{trace_id}`
- `GET /api/admin/diagnostics/traces/{trace_id}/export`
- `GET /api/admin/diagnostics/traces/stats/reasons`
- `POST /api/admin/diagnostics/files/{file_id}/retry-index`

member 角色访问上述接口应返回 403（由 `require_admin` 控制）。

---

## 12. 已验证项（本轮）

- 后端测试：`27 passed`。
- `POST /api/qa/ask` 相关 schema 与测试中的关键字段（`references_json` / `evidence_bundles` / agent 元字段）在后端代码中可达。
- diagnostics admin 路由与前端 API 路径一致。
- `scripts/eval_rag.py` 可执行（样例数据下可生成报告）。
- 修复了前端 `RetrievalMeta` 缺少 `selected_scope` 的类型错误，`npm run type-check` 通过。

---

## 13. 未验证项 / 限制

- 未在本环境完成端到端 UI 手工回归（无浏览器自动化工具）。
- 未完成真实容器启动验证（本轮主要做配置与静态一致性修复，未实际执行 `docker compose up` 全链路验收）。
- `smoke_check.py` 依赖正在运行的 API/DB；若服务未启动会连接失败。
- 前端 `npm run test:unit` 受 npm registry 403 限制（依赖未能完整安装）。

---

## 14. 相关文档

- `docs/deployment.md`
- `docs/troubleshooting.md`
- `docs/eval_rag.md`
- `docs/phase25_admin_diagnostics_and_smoke.md`
