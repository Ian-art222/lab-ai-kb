# Lab AI KB

私有化实验室知识库：**文件与目录治理** + **多格式原文索引（pgvector + 全文检索）** + **RAG 问答与可观测诊断**。后端 **FastAPI + SQLAlchemy + Alembic + PostgreSQL/pgvector**，前端 **Vue 3 + Vite + TypeScript + Element Plus + Pinia**。

---

## 功能概览

### 认证与用户

- **JWT** 登录；角色 **`root` / `admin` / `member`**。
- **`can_download`**：控制普通成员是否可下载文件（`root` / `admin` 始终视为可下载）。
- 用户管理：`root` 与 `admin` 可管理用户；部分高危操作仅 `root`（见下节）。

### 文件中心（Drive）

- **目录树**：支持多级文件夹；**空间模型**区分公共区与个人区（含管理员个人目录等 `scope` 语义）。
- **上传 / 下载 / 重命名 / 移动 / 复制 / 删除**；权限按目录与文件记录统一校验（`app/core/permissions.py`）。
- **批量下载**（ZIP）；列表项带 **`can_*` 能力位**，与后端校验一致。
- 前端路由：**`/files`**（卡片/导航等 UI 组件见 `apps/web/src/components/files/`）。

### 索引与知识块

- 支持对 **`txt` / `md` / `csv` / `tsv` / `pdf` / `docx`** 建立索引（具体以 `ingest_service` 为准）。
- **`knowledge_chunks`**：支持 **父子块**（`chunk_kind`）、**页码**（PDF 等）、**metadata_json**（段落结构、pipeline 版本等）。
- 可选 **结构化切块管线**（`ingest_structural_chunking_enabled` + `chunk_pipeline`）。
- 索引入口：**`POST /api/qa/ingest/file`**（异步由 FastAPI `BackgroundTasks` 触发，与文件中心上传解耦时可手动触发）。
- Embedding 使用 **`model_service` + `provider_adapters`**；未配置完整 embedding 时仍可完成文本块索引（带告警）。

### 问答（RAG）

- **`POST /api/qa/ask`**：作用域 **`all` / `folder` / `files`**，strict / 非 strict，引用与证据结构返回。
- 检索：**语义（pgvector）+ 词法（FTS）混合**、可配置阈值与候选规模；可选 **重排序（cross-encoder）**。
- **Query 理解 / 多查询扩展**（`query_understanding`）、**上下文打包**（`context_packing`）、**合成与护栏**（`qa_synthesis` / `qa_guardrails`）、**Agent 工作流**（`qa_agent_workflow`）等能力按配置组合启用。
- **会话**：创建会话、历史消息；检索过程可落 **trace / citation** 模型供诊断使用。

### 系统设置

- **`/settings`**（前端）：**仅 `root`** 可访问；模型、Embedding、批量大小等写入 **`system_settings`**。

### 管理员诊断

- **`/admin/diagnostics`**（前端）：**仅 `root`** 可访问。
- 接口前缀 **`/api/admin/diagnostics`**：trace 列表/详情/导出、原因统计、对指定文件 **retry-index** 等。

### 数据库与扩展

- **Alembic** 管理迁移；仓库中包含 **PDF 文献扩展表**（如 `pdf_documents`、`pdf_translation_tasks` 等）的迁移文件，用于后续「文献元数据 / 翻译任务 / 附件」等能力；**当前 HTTP 路由以 `app/main.py` 挂载为准**，若未挂载独立 `pdf` 路由，则仅数据库层就绪。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| API | FastAPI, SQLAlchemy 2, Alembic, PyJWT, PyPDF2, python-docx |
| 数据 | PostgreSQL 16, pgvector |
| 前端 | Vue 3, Vite, TypeScript, Element Plus, Pinia, Vue Router |
| 部署 | Docker Compose（`db` + `api` + `web`），可选 Nginx 配置见 `deploy/` |

---

## 仓库结构

```text
apps/
  api/                 # FastAPI 应用、服务层、迁移、测试
  web/                 # Vue 3 前端
docs/                  # 部署、阶段说明、评测与排障
evals/                 # 评测数据与报告样例
scripts/               # 运维脚本（如仅重建 web 容器）、辅助审计脚本
docker-compose.yml     # 默认编排与资源限制
```

更细的架构说明可参考 **`docs/architecture-audit.md`**。

---

## 环境要求

- Python **3.10+**
- Node.js **20+**（建议 22）
- PostgreSQL **16** + **pgvector**（本地或 Compose）

---

## 本地开发

### API

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # Windows: copy

# DATABASE_URL 指向已安装 pgvector 的 PostgreSQL
alembic upgrade head
python scripts/create_admin.py <username> '<password>'

uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Web

```bash
cd apps/web
npm install
cp .env.example .env
npm run dev -- --host 127.0.0.1 --port 5173
```

开发环境下 Vite 通常将 **`/api` 代理到** `http://127.0.0.1:8000`（以 `vite.config` 为准）。

---

## Docker Compose

### 准备

```bash
cp .env.example .env
cp apps/api/.env.example apps/api/.env
```

Compose 会通过环境变量覆盖容器内 **`DATABASE_URL`**（指向服务名 `db`）。**`CORS_ALLOWED_ORIGINS`** 需与实际浏览器访问前端的 Origin 一致（见根目录 `.env` / `docker-compose.yml` 说明）。

### 启动

```bash
docker compose up -d --build
```

**仅更新前端静态资源时**，请重建 web 容器，例如：

```bash
./scripts/docker-rebuild-web.sh
# 或
docker compose up -d --build --force-recreate web
```

### 默认端口

| 服务 | 地址 |
|------|------|
| Web | http://127.0.0.1:8080 |
| API | http://127.0.0.1:8000 |
| PostgreSQL | 127.0.0.1:5432 |

### 健康检查

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8080/health
```

---

## 数据库迁移

```bash
cd apps/api
alembic upgrade head
alembic current
```

---

## 测试与质量

```bash
# 后端
cd apps/api && pytest -q

# 前端类型检查
cd apps/web && npm run type-check

# 前端单元测试（需依赖安装完整）
cd apps/web && npm run test:unit
```

---

## 脚本与评测

| 说明 | 命令或路径 |
|------|------------|
| 基础 API smoke | `cd apps/api && python scripts/smoke_check.py` |
| 管理员诊断 smoke | 见 `docs/phase25_admin_diagnostics_and_smoke.md` |
| RAG 评测样例 | `cd apps/api && python scripts/eval_rag.py --help` |
| 检索打包等实验脚本 | `apps/api/scripts/smoke_context_packing.py` 等 |
| PDF 块页码审计（辅助） | `scripts/audit_pdf_chunk_pages.py` |

---

## HTTP API 速查（挂载于 `app/main.py`）

| 前缀 | 用途 |
|------|------|
| `/api/auth` | 登录、Token |
| `/api/files` | 目录、文件 CRUD、上传、下载、批量下载 |
| `/api/qa` | 问答、ingest、会话、索引状态 |
| `/api/users` | 用户管理 |
| `/api/settings` | 系统设置（权限见路由依赖） |
| `/api/admin/diagnostics` | 诊断与重索引（**root**） |

根路径 **`GET /`** 与 **`GET /health`** 返回服务存活信息。

---

## 相关文档

- `docs/deployment.md` — 部署
- `docs/troubleshooting.md` — 排障
- `docs/eval_rag.md` — RAG 评测说明
- `docs/phase25_admin_diagnostics_and_smoke.md` — 诊断与 smoke
- `docs/architecture-audit.md` — 架构审计记录

---

## 限制说明

- **异步任务**当前与 **FastAPI `BackgroundTasks`** 同进程；高负载场景需自行评估队列/Worker 方案。
- **扫描版 PDF** 无内嵌文本时，提取效果取决于是否另有 OCR 链路（当前以文本提取为主）。
- 完整 **E2E UI** 与 **生产环境 Compose 验收** 依赖你的部署与网络环境，请在目标环境执行健康检查与关键路径验证。
