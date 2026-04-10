# Lab AI KB

私有化实验室知识库：**文件与目录**、**多格式索引（PostgreSQL + pgvector + 全文检索）**、**RAG 问答**、**PDF 文献阅读与笔记**，以及 **root 级诊断与模型设置**。后端 **FastAPI + SQLAlchemy 2 + Alembic**，前端 **Vue 3 + Vite + TypeScript + Element Plus + Pinia**。

---

## 仓库审计摘要（当前形态）

| 领域 | 说明 |
|------|------|
| 部署 | `docker-compose.yml`：`db`（pgvector/pg16）+ `api` + `web`（Nginx 静态 + 反代示例见 `deploy/`） |
| 认证与权限 | JWT；角色 **`root` / `admin` / `member`**；目录与文件能力位与 `app/core/permissions.py` 一致 |
| 空间模型 | `home` 下 **`公共文件夹`**（`scope=public`）与 **`个人文件夹`**（`scope=private_root`）；管理员个人目录为 `admin_private`，由 `folder_spaces` 保证根节点 |
| 索引 | `ingest_service` + `chunk_pipeline`；`knowledge_chunks` 含语义向量列 **`embedding_vec`（vector(1024)）** 与 FTS；详见 `docs/ops-embedding-pgvector-dimensions.md` |
| 后台任务 | 索引进程与 **`BackgroundTasks`** 同进程；启动时与周期线程执行 **索引僵尸回收**（`index_stale_reclaim_service`，可配置间隔） |
| PDF | 路由挂载 **`/api/pdf-documents`**（`app/main.py`）：文献元数据、附件、批注、导出、文内问答等；前端 **PDF 阅读器 + 侧栏笔记**（Quill + 清洗逻辑） |
| 运维文档 | `docs/deployment.md`、`docs/troubleshooting.md`；**不再**包含已移除的 `docs/architecture-audit.md` |

---

## 功能概览

### 认证与用户

- **JWT** 登录；**`can_download`** 控制成员下载（`root` / `admin` 视为可下载）。
- 用户管理：高危操作仅 **`root`**。

### 文件中心（`/files`）

- 目录树与 **空间入口卡片**（公共 / 私人入口文案与 `scope` 一致）。
- 上传、下载、重命名、移动、复制、删除；批量 ZIP；列表带 **`can_*`** 与后端校验对齐。

### 索引与知识块

- 支持格式以 `ingest_service` 为准（含 **`txt` / `md` / `csv` / `tsv` / `pdf` / `docx`** 等）。
- 可选结构化切块、页码与 `metadata_json`。
- 手动/补索引：`POST /api/qa/ingest/file` 等（与上传流程可组合使用）。

### 问答（RAG）

- **`POST /api/qa/ask`**：作用域 **`all` / `folder` / `files`**；混合检索（向量 + 词法）、可配置重排序与护栏/合成链路。
- 会话、引用与诊断 trace（供管理员分析）。

### PDF 文献与笔记

- API：`/api/pdf-documents/...`（批注 CRUD、附件、Bib/RIS 导出、权限内预览等）。
- 前端：PDF 画布阅读、笔记编辑与聚合展示（具体组件见 `apps/web/src/components/pdf/`、`PdfReaderView.vue`）。

### 系统设置与诊断

- **`/settings`**：**仅 `root`**（模型、Embedding、批量参数等写入 `system_settings`）。
- **`/admin/diagnostics`**：**仅 `root`**；`/api/admin/diagnostics` 提供 trace、重试索引等。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| API | FastAPI, SQLAlchemy 2, Alembic, PyJWT, PyPDF2 / pypdf 生态、python-docx |
| 数据 | PostgreSQL 16, **pgvector** |
| 前端 | Vue 3, Vite, TypeScript, Element Plus, Pinia, Vue Router, pdfjs-dist, Vue Quill |
| 部署 | Docker Compose；可选 `deploy/nginx.lab-ai-kb.conf` |

---

## 仓库结构

```text
apps/
  api/                 # FastAPI、服务层、Alembic、脚本与测试
  web/                 # Vue 3 前端
docs/                  # 部署、阶段说明、评测、排障、向量维度说明
evals/                 # 评测数据与样例
scripts/               # 运维辅助脚本
docker-compose.yml     # 默认编排与资源限制
```

---

## 环境要求

- Python **3.10+**
- Node.js **20+**（建议 22，见 `apps/web/package.json` engines）
- PostgreSQL **16** + **pgvector**

---

## 本地开发

### API

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

alembic upgrade head
python scripts/create_admin.py <username> '<password>'

uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Web

```bash
cd apps/web
npm ci
cp .env.example .env
npm run dev -- --host 127.0.0.1 --port 5173
```

开发环境下 Vite 将 **`/api` 代理到** 本地 API（见 `apps/web/vite.config.ts`）。

---

## Docker Compose

### 准备

```bash
cp .env.example .env
cp apps/api/.env.example apps/api/.env
```

Compose 会覆盖容器内 **`DATABASE_URL`**。**`CORS_ALLOWED_ORIGINS`** 须与实际浏览器访问前端的 Origin 一致（`docker-compose.yml` / 根目录 `.env`）。

### 启动

```bash
docker compose up -d --build
```

仅更新前端静态资源时可重建 `web` 服务，例如：

```bash
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

若变更了 **embedding 维度**或列类型，须按 `docs/ops-embedding-pgvector-dimensions.md` 处理迁移与 **reindex**。

---

## 测试与质量

```bash
cd apps/api && pytest -q
cd apps/web && npm run type-check
cd apps/web && npm run test:unit
```

---

## 脚本与评测

| 说明 | 路径或命令 |
|------|------------|
| 基础 API smoke | `cd apps/api && python scripts/smoke_check.py` |
| 诊断 smoke | `docs/phase25_admin_diagnostics_and_smoke.md` |
| RAG 评测 | `cd apps/api && python scripts/eval_rag.py --help` |
| 向量列回填（在维度一致前提下） | `apps/api/scripts/backfill_embedding_vec_from_array.py` |

---

## HTTP API 速查

| 前缀 | 用途 |
|------|------|
| `/api/auth` | 登录、Token |
| `/api/files` | 目录、文件、上传、下载、批量下载 |
| `/api/qa` | 问答、ingest、会话、索引状态 |
| `/api/users` | 用户管理 |
| `/api/settings` | 系统设置（权限见路由） |
| `/api/admin/diagnostics` | 诊断与重索引（**root**） |
| `/api/pdf-documents` | PDF 文献、批注、附件、导出、文内问答 |

根路径 **`GET /`** 与 **`GET /health`** 返回存活信息。

---

## 相关文档

- [`docs/deployment.md`](docs/deployment.md) — 部署
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — 排障
- [`docs/eval_rag.md`](docs/eval_rag.md) — RAG 评测
- [`docs/phase25_admin_diagnostics_and_smoke.md`](docs/phase25_admin_diagnostics_and_smoke.md) — 诊断与 smoke
- [`docs/ops-embedding-pgvector-dimensions.md`](docs/ops-embedding-pgvector-dimensions.md) — **pgvector 维度与智谱 Embedding-3**

---

## 限制说明

- 异步索引与 **同进程** `BackgroundTasks` 共存；高负载请自行评估队列/Worker。
- 扫描版 PDF 无文本时效果取决于提取/OCR 链路（当前以文本提取为主）。
- 生产验收请在目标环境执行健康检查与关键路径（登录、上传、问答、PDF 打开）自测。
