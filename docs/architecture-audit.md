# Lab AI KB — 架构与功能审计（面向 PDF 阅读 / 协作 / 文献 AI 规划）

**审计日期**：以仓库当前代码为准（2026-04）  
**范围**：全栈真实实现；不假设未接通能力。  
**目标读者**：后续 PDF 模块 Tech Lead / 架构评审。

---

## 1. 项目总体审计结论

Lab AI KB 是一套**私有化部署**的「网盘式文件中心 + 文本索引 + RAG 问答 + root 级运维诊断」系统。后端为 **FastAPI + SQLAlchemy + Alembic + PostgreSQL/pgvector**，前端为 **Vue 3 + Vite + Element Plus + Pinia**，生产环境通过 **Docker Compose（db / api / web）** 与 **Nginx 反代静态 + `/api`** 交付。

架构上，**文件元数据与二进制**落在 `files` 表与 `UPLOAD_DIR`，**向量与全文检索**落在 `knowledge_chunks`（含 `embedding_vec`、`search_vector`、parent/child 结构），**问答会话与可观测性**落在 `qa_sessions` / `qa_messages` / `qa_retrieval_traces` / `qa_citations`。大模型与 Embedding 通过统一的 **`model_service.chat_completion` / `model_service.embed_texts` + `provider_adapters`** 访问外部 API；**Rerank 当前实现为进程内 `sentence_transformers.CrossEncoder`（可选）**，与 LLM 调用链分离。

**成熟度**：RAG 主链路（scope、检索融合、packing、引用、citation 落库、trace 落库）在代码层面完整；文件权限与目录空间（public / admin_private）已深度集成 `files` API 与 `core/permissions.py`。**未见**独立 Worker/Redis、**未见**在线 PDF 渲染/批注数据模型、**未见**自动「上传即索引」（索引依赖显式触发 `POST /api/qa/ingest/file` 或 UI 操作）。

**是否适合增量接入 PDF 模块**：适合以「扩展 `FileRecord` + 扩展阅读器路由 + 新增批注表 + 复用 `scope_type=files` 问答」为主轴渐进接入；需注意 **rerank 本地模型内存**、**ingest 与 API 同进程**、以及 **PDF 当前仅为 PyPDF2 文本抽取** 的天花板。

---

## 2. 技术栈清单

| 分层 | 技术 |
|------|------|
| **前端** | Vue 3、Vite、TypeScript、Vue Router、Pinia、Element Plus、`fetch` 封装（`apps/web/src/api/client.ts`）、全局设计 token（`apps/web/src/styles/design-tokens.css`） |
| **后端** | Python 3.12（Dockerfile）、FastAPI、Pydantic v2、SQLAlchemy 2.x、Alembic、python-jose（JWT）、PyPDF2、python-docx、pgvector（`Vector` + `TSVECTOR`） |
| **数据库** | PostgreSQL 16 + pgvector 扩展（镜像 `pgvector/pgvector:pg16`） |
| **AI / 模型访问** | `app/services/model_service.py`（`chat_completion`、`embed_texts`）、`app/services/provider_adapters.py`（OpenAI / OpenAI-Compatible / Anthropic / Gemini 等适配器） |
| **检索 / RAG** | `app/services/qa_service.py`（主编排）、`app/services/chunk_pipeline.py`（v3 结构切块）、`app/services/ingest_service.py`（解析→切块→embedding→写库）；配置大量来自 `app/core/config.py` 与 DB `system_settings` |
| **Rerank** | `qa_service._rerank_matches`：`sentence_transformers.CrossEncoder`（本地 CPU/GPU 模型，可选；未安装库则跳过） |
| **异步任务** | 仅 **FastAPI `BackgroundTasks`**：`/api/qa/ingest/file` 后台跑 `ingest_file_job`；**无** Celery/RQ/独立 worker |
| **部署** | `docker-compose.yml`：`db`、`api`、`web`；`apps/web/Dockerfile` 多阶段 build + Nginx；`deploy/nginx.lab-ai-kb.conf`：`/api` 反代、`/` SPA、`*.js/css` 长期缓存 |
| **缓存** | **无** Redis；无应用级 HTTP 缓存层 |

---

## 3. 目录与模块地图

| 路径 | 作用 |
|------|------|
| `apps/web/src/views/` | 页面：`HomeView`、`FilesView`、`ChatView`、`UsersView`、`SettingsView`、`LoginView`、`AdminDiagnosticsView` |
| `apps/web/src/api/*.ts` | API 封装：`client.ts`（`apiFetch`、401 处理）、`files.ts`、`qa.ts`、`users.ts`、`settings.ts`、`auth.ts`、`adminDiagnostics.ts` |
| `apps/web/src/stores/` | `auth.ts`、`system.ts`（设置缓存） |
| `apps/web/src/layouts/AdminLayout.vue` | 侧栏导航 + 顶栏 + `<main class="ds-page-main">` |
| `apps/web/src/components/files/` | `FilesDriveHeaderBar.vue`、`FolderCardNavigator.vue` |
| `apps/api/app/main.py` | 注册路由：`auth`、`files`、`qa`、`users`、`settings`、`admin_diagnostics` |
| `apps/api/app/api/` | HTTP 路由层 |
| `apps/api/app/services/` | 业务编排：`qa_service`、`ingest_service`、`model_service`、`provider_adapters`、`diagnostics_service`、`settings_service`、`chunk_pipeline` 等 |
| `apps/api/app/models/` | ORM：`user`、`folder`、`file_record`、`knowledge`（chunk/session/message/trace/citation）、`system_setting` |
| `apps/api/app/core/` | `config.py`、`auth.py`、`permissions.py` |
| `apps/api/alembic/` | 数据库迁移 |
| `docker-compose.yml` | 三服务编排；可选 `cpus`/`mem_limit`（若已配置） |
| `scripts/docker-rebuild-web.sh` | 前端镜像重建并 `up -d --force-recreate web` |

---

## 4. 前端架构与功能实现清单

**路由**（`apps/web/src/router/index.ts`）：`/login`、`/`、`/files`、`/chat`、`/users`（`requiresUserManager`）、`/settings` 与 `/admin/diagnostics`（`rootOnly`）。

| 页面 | 路由 | 主要依赖 | API / 行为概要 |
|------|------|-----------|----------------|
| **登录** | `/login` | `LoginView.vue` | `loginApi`（`api/auth.ts`）→ `authStore.setAuth` → 跳转 `/` |
| **首页** | `/` | `HomeView.vue` | `getDashboardApi`（`api/files.ts` → `GET /api/files/dashboard`）展示统计与最近文件 |
| **文件中心** | `/files` | `FilesView.vue`、`FilesDriveHeaderBar`、`FolderCardNavigator` | `files.ts`：`/files/folders/children`、`upload`、`download`、`batch-download`、移动/复制/删除等；索引：`qa.ts` → `POST /api/qa/ingest/file`；元数据抽屉 `GET /files/{id}/meta`；切块诊断 root：`GET /files/{id}/chunks/diagnostics` |
| **RAG 问答** | `/chat` | `ChatView.vue` | `qa.ts`：`POST /api/qa/ask`、会话列表与消息、`ingestFileApi`；UI 展示 `retrieval_meta`、引用、coverage 等 |
| **用户管理** | `/users` | `UsersView.vue` | `users.ts`：`/users`、`/users/me`、CRUD、状态、重置密码（需 `canManageUsers`） |
| **系统设置** | `/settings` | `SettingsView.vue` | `settings.ts`：`GET/PATCH /api/settings`、LLM/Embedding 测试接口（**仅 root**，与路由一致） |
| **诊断中心** | `/admin/diagnostics` | `AdminDiagnosticsView.vue` | `adminDiagnostics.ts` → `/api/admin/diagnostics/*`（**后端强制 `require_root`**，与前端 `rootOnly` 一致） |

**鉴权流转**：`apiFetch` 附加 `Authorization: Bearer <token>`（`localStorage`）；401 清 token 并跳转登录页。角色来自登录响应与 `GET /users/me` 的 `syncFromMe`（含 `userId`）。

**设计系统**：`main.ts` 引入顺序为 Element Plus CSS → `design-tokens.css` → `style.css`。

**PDF 阅读器挂载建议（基于现状）**：

- **最自然**：新路由如 `/reader/:fileId` 或在 `FilesView` 内嵌抽屉/全屏层（需新组件）；与现有「下载」互补，因**当前无 Range/预览专用 API**。
- **复用问答**：`ChatView` 已支持按文件范围提问；可 deep-link 带 `file_ids` 或 session scope。

---

## 5. 后端架构与功能实现清单

| 模块 | 路由前缀 | Service / 核心逻辑 | 权限要点 |
|------|-----------|-------------------|----------|
| **认证** | `/api/auth` | JWT 签发与校验（`core/auth.py`） | `get_current_user` |
| **用户** | `/api/users` | 用户 CRUD、me | `require_user_manager` / `require_root`（视端点） |
| **设置** | `/api/settings` | `settings_service`、连接测试 | 修改与测试多为 **root**（见 `api/settings.py`） |
| **文件** | `/api/files` | 文件夹树、列表、上传（写磁盘 + `FileRecord`）、下载、批量 ZIP、移动/复制/删除、chunk diagnostics 等 | `core/permissions.py` 细粒度能力（上传/下载/结构管理/空间 scope） |
| **问答** | `/api/qa` | `qa_service.ask_question`、`ingest_file` BackgroundTasks、`sessions`/`messages` | `AskRequest` scope 校验（`_ensure_ask_scope`） |
| **诊断** | `/api/admin/diagnostics` | `diagnostics_service`：trace 列表/详情/导出、reason 统计、retry reindex | **`require_root`** |

**说明**：仓库根 `README.md` 曾写「管理员诊断接口强制 admin」与**当前代码不一致**；以 `admin_diagnostics.py` 的 `require_root` 为准。

---

## 6. 数据库与核心表关系

| 表名 | 职责 |
|------|------|
| **users** | 用户、`role`（root/admin/member）、`can_download`、`is_active` |
| **folders** | 目录树、`scope`（public / admin_private）、`owner_user_id` |
| **files** | 文件元数据、`storage_path`、`folder_id`、**索引状态字段**（`index_status`、`indexed_at`、`content_hash` 等） |
| **knowledge_chunks** | RAG 核心：**`file_id` → files**；`chunk_index`；`content`；`embedding` / **`embedding_vec`**；**`search_vector`**；**`parent_chunk_id`**；`chunk_kind`；`page_number`；`metadata_json`（JSONB） |
| **qa_sessions** | 用户会话、`scope_type`、`folder_id` |
| **qa_messages** | 问答消息、`references_json` |
| **qa_retrieval_traces** | 每次 ask 的 trace（检索参数、融合、rerank、失败/拒答原因、`debug_json` 等） |
| **qa_citations** | 归一化引用（`message_id`、`file_id`、`chunk_id`、`page_number` 等） |
| **system_settings** | 单行配置：LLM/Embedding 提供商与密钥、`qa_enabled`、UI 偏好、最近测试状态等 |

**PDF 文献对象**：当前**无独立「文献」表**；PDF 与普通文件同为 **`files` + `file_type=pdf`**。扩展点包括：`metadata_json`（chunk 级）、`FileRecord` 新增列（文献题录）、或关联新表 `document_artifacts`（需迁移）。

---

## 7. 文件上传 → 解析/索引 → RAG 问答全链路（真实流程）

1. **上传** `POST /api/files/upload`（`files.py`）：写入 `UPLOAD_DIR` 下随机文件名，插入 **`files` 行**，`index_status="pending"`。**不自动触发索引**。
2. **触发索引**（显式）：`POST /api/qa/ingest/file`（`qa.py`）：`BackgroundTasks` 调用 `_run_ingest_in_background` → `ingest_service.ingest_file_job`。
3. **解析**（`ingest_service._extract_text`）：  
   - **PDF**：`PyPDF2.PdfReader` 逐页 `extract_text()`，无 OCR、无布局坐标。  
   - **DOCX**：`python-docx`。  
   - **TXT/MD/CSV/TSV**：直接读文本。
4. **切块**（`chunk_pipeline` + ingest）：结构管道 **parent/child**；写入 **`knowledge_chunks`**，维护 **`parent_chunk_id`**、`chunk_kind`、`page_number`（PDF 页码在管道中按块传递，取决于分段逻辑）。
5. **Embedding**：`model_service.embed_texts` 批量调用外部 API，写入 `embedding` 与维度匹配的 `embedding_vec`。
6. **问答** `POST /api/qa/ask`：`qa_service.ask_question` 加载 `system_settings`，`embed_texts` 对查询变体编码，按 **scope** 过滤可检索 `file_id`，执行 **向量 + 全文（模式依赖配置）** 融合、可选 **CrossEncoder rerank**、packing、再 **`chat_completion`** 生成答案；落库 message、citation、trace。

---

## 8. LLM / Embedding / RAG 能力复用分析（面向 PDF）

| 能力 | 复用方式 | 说明 |
|------|-----------|------|
| **文献内问答** | **高** | 已有 `AskRequest.scope_type="files"` + `file_ids` + 后端 `_ensure_ask_scope` / `_collect_retrievable_file_ids` |
| **引用与 chunk 定位** | **高** | `references` 含 `chunk_id`、`page_number`、`section_title`；`qa_citations` 可支撑侧栏高亮（需前端对接） |
| **全文翻译** | **中** | 无专用接口；可复用 **`chat_completion`** 新 prompt，需注意 **token 长度与费用**；长文应分段或异步任务（当前无标准长任务队列） |
| **划词翻译** | **中** | 同上；延迟敏感，需独立轻量调用与缓存策略（未实现） |
| **Embedding** | **高** | `embed_texts` 统一入口；PDF 新粒度（句/块）仍回写 `knowledge_chunks` 或扩展表 |
| **Rerank** | **低-中** | 依赖 **本地 CrossEncoder**；PDF 协作部署时要评估 **内存与 CPU**（与 8G 预算冲突风险） |
| **流式输出** | **低** | 当前 `chat_completion` 返回完整 `str`；SSE/WebSocket **非现状** |

---

## 9. PDF 模块接入建议（基于代码，非空想）

| 问题 | 建议 |
|------|------|
| **文献主表** | **优先复用 `files`**，用 `file_type`/`mime_type` 区分；题录（DOI、作者）用 **新增列或 `literature_metadata` 表** 与 `file_id` 1:1 |
| **页/段/block 索引** | **优先接现有 `knowledge_chunks`**：`page_number`、`metadata_json` 已存在；复杂版式可扩展 `metadata_json` 或子表 **`chunk_spans`**（页码矩形——需新迁移） |
| **阅读器路由** | 新建 **`/reader/:fileId`**（或 `/files/:id/read`）最清晰；与 `FilesView` 解耦，便于权限中间件 |
| **文献问答** | 复用 **`POST /api/qa/ask`**，`scope_type=files`，`file_ids=[pdfId]` |
| **全文翻译** | 复用 **`model_service.chat_completion`**；建议 **新 service** 封装「分段、合并、进度」，避免塞进 `qa_service` |
| **批注** | **必须新表**（如 `document_annotations`：`file_id`、`user_id`、`scope` 公共/私有、`payload` JSON）；权限复用 **`can_view_folder` / `user_may_access_file_record`**，**无**现成「笔记可见性」模型 |

---

## 10. 风险与技术债清单（按优先级）

1. **索引与 API 同进程**：大文件 ingest 占用 **api 容器 CPU/内存**；PDF 加深解析后风险上升。长期宜 **独立 worker** 或至少限流/队列。  
2. **Rerank 本地模型**：CrossEncoder 与 **8G 内存预算**、**4 CPU** 可能冲突；PDF 上线前建议可配置关闭或换云端 rerank。  
3. **PDF 抽取质量**：PyPDF2 纯文本，**扫描件/复杂排版**效果差；文献场景常需 **OCR 或专用解析 pipeline**（与现 ingest 深度耦合）。  
4. **`qa_service.py` 体量极大**：编排、检索、packing、guardrail 同文件，**接 PDF 特性时易继续膨胀**；建议新功能拆 **pdf_translation_service** / **annotation_service**。  
5. **上传与索引分离**：用户易忘记点「建索引」；产品层需明确引导或可选自动 ingest（有成本与权限含义）。  
6. **无流式回答**：体验与主流 Chat 产品有差距；PDF 边读边问若加流式，需改 `chat_completion` 与前端。  
7. **文档与代码**：README 对诊断权限描述 **过时**（应为 root）。

---

## 11. 文档与代码变更记录

- **新增**：`docs/architecture-audit.md`（本文件）  
- **本轮**：未修改业务代码  

---

## 附录：关键代码锚点（便于跳转）

- FastAPI 入口：`apps/api/app/main.py`  
- 问答入口：`apps/api/app/api/qa.py` → `run_qa` / `ingest_file`  
- RAG 编排：`apps/api/app/services/qa_service.py`（`ask_question`、`_rerank_matches`）  
- LLM/Embedding：`apps/api/app/services/model_service.py`  
- 适配器注册：`apps/api/app/services/provider_adapters.py`（`get_provider_adapter`）  
- 索引任务：`apps/api/app/services/ingest_service.py`（`ingest_file_job`、`_extract_text` PDF）  
- Chunk 模型：`apps/api/app/models/knowledge.py`（`KnowledgeChunk`）  
- 文件模型：`apps/api/app/models/file_record.py`  
- 前端 API 基类：`apps/web/src/api/client.ts`  
- 前端问答类型：`apps/web/src/api/qa.ts`  
