# Lab AI KB

Lab AI KB 是一个面向团队内部的私有化**文本型 RAG**知识库系统，技术栈为 **FastAPI + PostgreSQL + pgvector + Vue 3 + Element Plus**。

> 当前定位：工程可运行、可部署、可回归的文本知识库问答系统；不是多模态平台。

---

## 1. 项目简介

本项目用于管理文档、建立索引并进行基于文档证据的问答。后端负责文件管理、索引和问答链路，前端提供文件中心、问答界面、用户与系统配置页面。

当前已经覆盖：
- 文件管理（目录树、上传、下载、移动、删除、详情）
- 文件索引（建立索引、重建索引、索引状态追踪）
- RAG 问答（scope 控制、strict/non-strict、引用返回）
- 多 Provider 配置（聊天模型与检索 embedding 分离）
- 评测脚本与 source diversity 回归样例

---

## 2. 当前能力概览

### 文件能力
- 支持文件类型：`txt` / `md` / `pdf`（文本型 PDF）/ `docx`
- 支持单文件上传与单文件下载
- 支持批量上传（前端逐文件上传）
- 支持批量下载（后端打包 ZIP）
- 前端提供上传/下载进度条与百分比显示

### RAG 能力
- 检索模式：`semantic` / `lexical` / `hybrid`
- pgvector 检索 + 失败回退
- rerank（可开关）
- strict / non-strict 回答策略
- source diversity control（相关性优先，不强制多来源）

### 平台能力
- JWT 登录鉴权
- 用户与角色管理
- 系统设置（provider/model/retrieval 参数）
- 首页运行状态与近期记录

---

## 3. 边界与不支持项

本仓库当前只做文本型 RAG，明确不做：
- 多模态问答
- OCR
- 图片理解
- 表格图片识别
- 音视频解析
- 视觉模型推理

如上传扫描版 PDF，系统不会执行 OCR。

---

## 4. 目录结构

```text
apps/
  api/      # FastAPI 后端
  web/      # Vue 3 + Element Plus 前端
docs/
  deployment.md
  troubleshooting.md
  eval_rag.md
```

常用路径：
- 后端环境变量示例：`apps/api/.env.example`
- 前端环境变量示例：`apps/web/.env.example`
- 评测样例：
  - `apps/api/evals/source_diversity_eval.sample.jsonl`
  - `apps/api/evals/source_diversity_regression.sample.jsonl`

---

## 5. 快速开始

## 5.1 后端启动

```bash
cd apps/api
python -m venv .venv
# Windows
.venv\Scripts\pip install -r requirements.txt
# Linux/macOS
# source .venv/bin/activate && pip install -r requirements.txt

# 准备配置
copy .env.example .env

# 执行迁移
.venv\Scripts\alembic upgrade head

# 创建管理员
.venv\Scripts\python scripts\create_admin.py admin your-password

# 启动
.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 5.2 前端启动

```bash
cd apps/web
npm install
copy .env.example .env
npm run dev -- --host 127.0.0.1 --port 5173
```

本地默认通过 Vite 代理访问后端：`/api -> http://127.0.0.1:8000`。

---

## 6. 环境变量与关键配置

### 6.1 后端环境变量

后端读取 `apps/api/.env`，关键项：
- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `UPLOAD_DIR`
- `LLM_*`（聊天）
- `EMBEDDING_*`（检索 embedding）
- `EMBED_BATCH_SIZE` / `EMBED_RETRY_TIMES` / `EMBED_BATCH_DELAY`
- `QA_*`（检索、阈值、rerank、source diversity）

### 6.2 前端环境变量

`apps/web/.env`：
- `VITE_API_BASE_URL=`

本地开发建议留空，优先使用 Vite 代理。

---

## 7. RAG 能力说明

### 7.1 聊天模型与检索 embedding 分离

- `llm_*`：控制回答生成
- `embedding_*`：控制索引与检索向量空间

**重要**：上线后不应随意切换 `embedding_provider` / `embedding_model`。若切换，需要重建旧索引。

### 7.2 Source Diversity Control

目标：减少“同一文档多个相邻 chunk 霸榜”问题，同时保持相关性优先。

核心策略：
- per-doc cap
- dominance guardrail
- adjacent redundancy suppression
- diversity rerank（可选）
- doc-aware selection

关键参数可在 `apps/api/app/core/config.py` 查阅（`QA_MAX_CHUNKS_PER_DOC`、`QA_DIVERSITY_RERANK_ENABLED`、`QA_SINGLE_DOC_DOMINANCE_RATIO` 等）。

---

## 8. Provider / 模型接入说明

当前项目支持在系统设置页配置多 Provider（含 openai-compatible、gemini、qwen 等路径）。

推荐预上线默认组合（见 `docs/deployment.md`）：
- Chat: `gemini / gemini-2.5-flash`
- Retrieval embedding: `qwen / text-embedding-v4`

原则：
- 聊天模型可按业务切换
- 检索 embedding 标准应固定

---

## 9. 验证与回归（smoke / eval）

### 9.1 Smoke Check

```bash
cd apps/api
.venv\Scripts\python scripts\smoke_check.py
```

### 9.2 RAG 评测

```bash
cd apps/api
python scripts/eval_rag.py --input evals/source_diversity_eval.sample.jsonl --output scripts/eval_source_diversity_report.json
```

说明：
- 样例文件是模板，不包含真实业务数据。
- 无真实已索引数据时，不应伪造 baseline/optimized 数值结论。
- 详细说明见 `docs/eval_rag.md`。

---

## 10. 部署 / 排障入口

- 部署文档：`docs/deployment.md`
- 排障文档：`docs/troubleshooting.md`

常见问题优先检查：
1. 后端是否可访问 `http://127.0.0.1:8000/docs`
2. Alembic 是否已迁移到 head
3. 前端是否误配置了 `VITE_API_BASE_URL`
4. 当前索引标准是否与已索引文件一致

---

## 11. 适用场景与限制

适用场景：
- 团队内部知识文档检索问答
- 中小规模文本资料归档与证据化问答
- 需要本地部署、可控配置和可回归验证的场景

当前限制：
- 非文本内容能力有限（不做 OCR/多模态）
- 下载进度百分比依赖浏览器对 `Content-Length` 的可计算性
- 评测结论依赖真实索引数据，不可仅凭样例模板得出线上质量结论


## 12. Docker Compose（单机部署）

仓库已提供可直接部署的 `web + api + db` Compose 方案：

- 启动文档见 `docs/deployment.md` 的“Docker Compose 部署（单机 2 CPU / 4GB）”章节
- 默认仅暴露 `127.0.0.1:8080`，便于宿主机再反向代理
- LLM / embedding 仍通过外部 Provider API，不在本机推理

