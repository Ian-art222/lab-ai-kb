# Lab AI KB

面向实验室内部成员的私有化知识库系统，当前已具备文件管理、异步索引、最小 RAG 问答、会话历史、用户管理和系统设置能力。

## 目录结构

- `apps/api`: FastAPI 后端
- `apps/web`: Vue 3 + Element Plus 前端

## 环境变量示例

- 后端示例：`apps/api/.env.example`
- 前端示例：`apps/web/.env.example`
- 部署说明：`docs/deployment.md`
- 排障说明：`docs/troubleshooting.md`

## 预上线默认建议

- 推荐默认聊天模型：`gemini:gemini-2.5-flash`
- 推荐默认 retrieval embedding 标准：`qwen:text-embedding-v4`
- 推荐默认 `embedding_batch_size`：`10`

关键原则：

- `llm_*` 只影响回答生成，可切换
- `embedding_*` 定义知识库检索向量空间，上线后不应频繁切换
- 切换 `embedding_provider` / `embedding_model` 后，需要重建旧索引

## 后端环境变量

后端配置读取 `apps/api/.env`。当前至少建议配置这些变量：

```env
APP_NAME=Lab AI KB API
APP_ENV=dev
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/lab_ai_kb
JWT_SECRET_KEY=please-change-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440
UPLOAD_DIR=uploads
EMBED_BATCH_SIZE=10
EMBED_RETRY_TIMES=2
EMBED_RETRY_BASE_DELAY=1.0
EMBED_BATCH_DELAY=0.25
```

说明：

- `DATABASE_URL` 指向 PostgreSQL
- `JWT_SECRET_KEY` 生产环境必须修改
- `APP_ENV` 建议测试环境显式设置为 `test`
- `UPLOAD_DIR` 为文件上传与索引读取目录，默认相对 `apps/api` 为 `uploads`
- LLM / Embedding 推荐在系统设置页中维护；环境变量主要作为 fallback / 初始值
- `EMBED_BATCH_SIZE` 只有在系统设置 `embedding_batch_size` 为空时才会生效
- 若默认 retrieval embedding 采用 Qwen / DashScope，建议 `EMBED_BATCH_SIZE=10`
- `EMBED_RETRY_TIMES` / `EMBED_RETRY_BASE_DELAY` / `EMBED_BATCH_DELAY` 用于大文件索引时的最小退避重试与轻量节流

### RAG 工程化关键配置（新增）

以下配置位于 `apps/api/app/core/config.py`，可通过后端环境变量覆盖：

- `QA_RETRIEVAL_MODE`：`semantic | lexical | hybrid`（默认 `hybrid`）
- `QA_PGVECTOR_RETRIEVAL_ENABLED`：是否启用 pgvector ANN 主链路（默认开启）
- `QA_PGVECTOR_SEMANTIC_ENABLED`：是否允许走 pgvector 语义检索（默认开启）
- `QA_PGVECTOR_PROBE_LIMIT`：ANN 粗召回上限（默认 `256`）
- `QA_SEMANTIC_THRESHOLD` / `QA_LEXICAL_THRESHOLD` / `QA_HYBRID_THRESHOLD`：不同检索模式的证据阈值
- `QA_RERANK_ENABLED`：是否默认启用 rerank（默认开启，可按环境关闭）
- `QA_RERANK_TOP_N`：rerank 处理候选上限
- `QA_RERANK_LATENCY_BUDGET_MS`：rerank 软延迟预算
- `QA_MAX_CHUNKS_PER_DOC`：单文档在上下文中可保留的 chunk 上限（默认 `2`）
- `QA_TARGET_DISTINCT_DOCS`：优先覆盖的目标来源文档数（默认 `3`）
- `QA_MIN_DISTINCT_DOCS_FOR_MULTI_SOURCE`：触发多来源倾向前的最小候选文档数（默认 `2`）
- `QA_SINGLE_DOC_DOMINANCE_RATIO`：单文档证据优势比阈值（默认 `1.6`，触发后允许单来源主导）
- `QA_DIVERSITY_RERANK_ENABLED`：是否开启轻量多样性重排（默认关闭）
- `QA_DIVERSITY_LAMBDA`：多样性重排中“相关性优先”的权重（`0~1`，默认 `0.75`）
- `QA_DIVERSITY_FETCH_K`：多样性重排参与候选数（默认 `24`）
- `QA_REDUNDANCY_SIM_THRESHOLD`：同文档相邻 chunk 去冗余的文本相似度阈值（默认 `0.9`）
- `QA_REDUNDANCY_ADJACENT_WINDOW`：相邻 chunk 去冗余窗口（默认 `1`）
- `QA_QUERY_EXPANSION_ENABLED`：是否启用轻量 query expansion（默认关闭）
- `QA_QUERY_EXPANSION_MAX_QUERIES`：扩展 query 数上限
- `QA_STRICT_MIN_CITATIONS`：严格模式最低引用条数
- `QA_MIN_GROUNDED_CITATIONS`：非严格模式下进入知识库回答的最低引用条数（不足则回退通用回答）
- `INGEST_CHUNK_SIZE` / `INGEST_CHUNK_OVERLAP` / `INGEST_MIN_CHUNK_CHARS` / `INGEST_MAX_INDEX_TEXT_CHARS`：文本型分块与截断策略
- `INGEST_PDF_MIN_CHARS_PER_PAGE`：文本型 PDF 最小页面字符阈值（用于识别疑似扫描件并记录降级日志）

说明：

- 当 pgvector 检索不可用（数据库、扩展或查询异常）时，会自动回退到应用层 cosine 检索，保证主链路可用性。
- 系统日志会记录当前检索策略、召回数量、阈值和 rerank 是否执行，便于回归与排障。
- Source diversity control 的目标是“相关性优先 + 抑制同文档霸榜”，而不是强制每次多文档引用。
  - 单文档证据明显更强且足够回答时，会被 dominance guardrail 保护。
  - 多文档存在互补证据时，会提升上下文来源覆盖，减少相邻重复 chunk 占满 context。
  - 可通过关闭 `QA_DIVERSITY_RERANK_ENABLED` 或将 `QA_MAX_CHUNKS_PER_DOC` 调大来回退到更保守策略。
- 当前仅支持文本型解析：`txt/md/pdf/docx`；不支持 OCR、图片理解和多模态解析。

### Source Diversity Control（工程说明 + 验证跑法）

这套能力的目标是：减少“同一文档多个相邻/高度相似 chunk 占满 topK 与 context”的情况。  
它**不是**强制多文档引用，也不追求“文档数越多越好”。

设计原则：

- 单文档证据足够且更强时，允许单来源回答（由 dominance guardrail 保护）。
- 多文档存在互补证据时，优先综合多个来源。
- 整体仍然相关性优先；多样性只是一层轻量平衡。
- strict 模式下若证据不足，仍应拒答或保守回答。

关键机制：

- `per-doc cap`：限制单文档 chunk 数，避免 context 被单篇文档淹没。
- `dominance guardrail`：当首来源显著更强时，不为了“凑多来源”引入噪声。
- `adjacent redundancy suppression`：抑制同文档相邻且高重叠 chunk。
- `diversity rerank`（可开关）：在相关性前提下轻量拉开来源覆盖。
- `doc-aware selection`：从候选中先做文档感知选择，再进入 context packing。

主要配置项（含作用）：

- `QA_MAX_CHUNKS_PER_DOC`：单文档最多保留多少 chunk；越小越能抑制单文档 flood。
- `QA_TARGET_DISTINCT_DOCS`：优先覆盖的目标来源文档数，不是强制值。
- `QA_MIN_DISTINCT_DOCS_FOR_MULTI_SOURCE`：候选来源不足时不强推多来源。
- `QA_SINGLE_DOC_DOMINANCE_RATIO`：首来源相对次来源的优势阈值；越小越容易触发“单源可主导”。
- `QA_DIVERSITY_RERANK_ENABLED`：开启/关闭轻量多样性重排。
- `QA_DIVERSITY_LAMBDA`：多样性重排里“相关性权重”；越高越保守。
- `QA_DIVERSITY_FETCH_K`：参与多样性重排的候选窗口。
- `QA_REDUNDANCY_SIM_THRESHOLD`：相邻冗余判定阈值；越低越激进去重。

#### baseline vs optimized：如何验证

1) 准备数据：

- 本仓库提供评测样例模板：
  - `apps/api/evals/source_diversity_eval.sample.jsonl`
  - `apps/api/evals/source_diversity_regression.sample.jsonl`
- 注意：仓库**不附带真实已索引数据库内容**；上述 JSONL 仅是问题模板。

2) baseline 配置示例（更接近“无多样性约束”）：

```env
QA_DIVERSITY_RERANK_ENABLED=false
QA_MAX_CHUNKS_PER_DOC=999
QA_TARGET_DISTINCT_DOCS=1
QA_MIN_DISTINCT_DOCS_FOR_MULTI_SOURCE=1
QA_SINGLE_DOC_DOMINANCE_RATIO=999
QA_REDUNDANCY_SIM_THRESHOLD=0.999
```

3) optimized 配置示例（启用本轮能力）：

```env
QA_DIVERSITY_RERANK_ENABLED=true
QA_DIVERSITY_LAMBDA=0.18
QA_DIVERSITY_FETCH_K=24
QA_MAX_CHUNKS_PER_DOC=2
QA_TARGET_DISTINCT_DOCS=3
QA_MIN_DISTINCT_DOCS_FOR_MULTI_SOURCE=2
QA_SINGLE_DOC_DOMINANCE_RATIO=1.35
QA_REDUNDANCY_SIM_THRESHOLD=0.92
```

4) 运行 eval（两轮：先 baseline，再 optimized）：

```bash
cd apps/api
python scripts/eval_rag.py --input evals/source_diversity_eval.sample.jsonl --output scripts/eval_source_diversity_baseline.json
python scripts/eval_rag.py --input evals/source_diversity_eval.sample.jsonl --output scripts/eval_source_diversity_optimized.json
```

5) 重点观察指标：

- `distinct_docs_in_topk`
- `distinct_docs_in_context`
- `same_doc_chunk_ratio`
- `adjacent_chunk_redundancy_rate`
- `multi_source_answer_rate`
- `citation_source_diversity`
- `single_source_when_sufficient_rate`
- `unsupported_multi_source_rate`
- `latency_p50_ms`
- `latency_p95_ms`

结论要求：没有真实已索引数据时，不应伪造 baseline vs optimized 数值；只能报告“样例与跑法已准备，待真实数据验证”。

## 前端环境变量

前端当前支持：

```env
VITE_API_BASE_URL=
```

说明：

- 本地开发默认留空，前端会走内置 Vite proxy：`/api -> http://127.0.0.1:8000`
- 只有在前后端部署在不同地址时，才建议在 `apps/web/.env` 中显式配置
- 如果 `apps/web/.env` 残留旧的 `VITE_API_BASE_URL`，它会覆盖 proxy 行为
- 修改后需要重启前端开发服务

## 安装与启动

### 1. 后端

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

准备配置文件：

```bash
copy .env.example .env
```

执行迁移：

```bash
.venv\Scripts\alembic upgrade head
```

启动服务：

```bash
.venv\Scripts\uvicorn app.main:app --reload
```

### 2. 前端

```bash
cd apps/web
npm install
npm run dev
```

如需自定义 API 地址：

```bash
copy .env.example .env
```

默认开发地址：

- 后端：`http://127.0.0.1:8000`
- 前端：`http://127.0.0.1:5173`

## Migration 说明

当前使用 Alembic 管理迁移，直接执行：

```bash
cd apps/api
.venv\Scripts\alembic upgrade head
```

Alembic 会按 revision 链自动完成顺序迁移；当前最新 head 已包含：

- 用户与系统设置
- 文件物理存储字段
- RAG chunk / QA 会话表
- 索引 warning 与唯一约束
- 最近 QA 状态
- 最近模型测试状态
- `embedding_batch_size` 系统设置化
- 文件级索引元数据：
  - `index_embedding_provider`
  - `index_embedding_model`
  - `index_embedding_dimension`

推荐初始化顺序：

1. 创建 PostgreSQL 数据库
2. 配置 `apps/api/.env`
3. 安装后端依赖
4. 执行 `alembic upgrade head`
5. 创建管理员账号
6. 启动后端
7. 配置前端 `.env`
8. 启动前端

## 管理员初始化

已提供脚本：

```bash
cd apps/api
.venv\Scripts\python scripts\create_admin.py admin your-password
```

作用：

- 用户不存在时创建新的管理员
- 用户已存在时重置密码并提升为管理员

建议首次启动后先执行一次，再登录系统进行后续配置。

## 首次配置建议

1. 使用管理员账号登录
2. 进入“系统设置”
3. 配置：
   - Chat / LLM 配置：
     - `LLM API Base URL`
     - `LLM Model`
     - `LLM API Key`
   - Retrieval Embedding 配置：
     - `Embedding API Base URL`
     - `Embedding Model`
     - `Embedding API Key`
     - `Embedding Batch Size`
4. 先分别执行“测试连接”
5. 打开 `QA 开关`
6. 上传文件并建立索引后再进入问答页

注意：

- 切换聊天模型不会影响已建立的索引
- 切换 `embedding_provider` / `embedding_model` 会改变知识库索引标准，旧文件通常需要重建索引

## 当前 Provider 支持矩阵

| Provider | Chat | Embeddings | Settings 测试连接 | Ingest / Index | QA | 当前状态 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OpenAI | 已适配 | 已适配 | 已适配 | 已适配 | 已适配 | 已适配但未真实凭证验证 | 当前环境缺少真实 OpenAI 凭证，只验证了错误路径与协议映射 |
| Gemini | 已真实跑通 | 已真实跑通 | 已真实跑通 | 已真实跑通 | 已真实跑通 | 已真实跑通 | 支持原生 `generateContent` / `batchEmbedContents` |
| Anthropic | 已适配 | 不支持 | Chat 已适配，Embedding 明确拒绝 | 不支持 embeddings 索引 | 不支持依赖 embeddings 的 QA 主链 | 已适配但未真实凭证验证 | 当前仅支持 chat；embeddings 已在前后端显式阻止 |
| OpenAI-compatible | 已真实跑通 | 已真实跑通 | 已真实跑通 | 已真实跑通 | 已真实跑通 | 已真实跑通 | 适用于 OpenAI 兼容接口 |
| DeepSeek | 通过 alias 真实测试连接 | 通过 alias 真实测试连接 | 已真实测试 | 可复用 OpenAI-compatible | 可复用 OpenAI-compatible | alias 已验证 | 当前用统一 OpenAI-compatible 适配层接入 |
| Qwen / DashScope | 通过 alias 真实测试连接 | 通过 alias 真实测试连接 | 已真实测试 | 可复用 OpenAI-compatible | 可复用 OpenAI-compatible | alias 已验证 | 当前用统一 OpenAI-compatible 适配层接入 |
| Kimi | 已适配 | 已适配 | 未在当前环境真实凭证验证 | 可复用 OpenAI-compatible | 可复用 OpenAI-compatible | alias 已适配 | 需要真实账号再做联调 |
| Tencent Hunyuan | 已适配 | 已适配 | 未在当前环境真实凭证验证 | 可复用 OpenAI-compatible | 可复用 OpenAI-compatible | alias 已适配 | 需要真实账号再做联调 |

说明：

- “已真实跑通”表示当前仓库已经通过真实保存配置、测试连接、索引或问答链路验证。
- “已适配但未真实凭证验证”表示协议与错误路径已验证，但当前环境缺少对应 provider 的真实可用账号。
- Anthropic 当前只纳入 chat 适配，不纳入 embeddings 能力。

## 固定 Retrieval Embedding 标准

当前项目已经收敛为：

- 文件建立索引永远使用 `embedding_*`
- QA query embedding 永远使用 `embedding_*`
- 聊天回答永远使用 `llm_*`

当前推荐默认上线标准：

- `embedding_provider = qwen`
- `embedding_model = text-embedding-v4`
- `embedding_batch_size = 10`

运行规则：

- 未索引文件会被静默跳过
- 旧索引标准文件会被静默跳过
- 只有当当前范围内没有任何兼容当前 retrieval 标准的已索引文件时，QA 才会报错

上线建议：

- 聊天模型可以切换
- retrieval embedding 标准不要频繁切换
- 一旦切换 retrieval embedding 标准，必须重建相关文献索引

## Provider 架构说明

当前后端已建立最小多 provider 适配层，核心目标是让业务层只依赖统一入口，而不是直接拼接各家协议：

- 统一入口：
  - `app/services/model_service.py`
  - 业务侧继续调用 `chat_completion()` / `embed_texts()`
- provider 适配层：
  - `app/services/provider_adapters.py`
- 当前 adapter：
  - `OpenAIAdapter`
  - `AnthropicAdapter`
  - `GeminiAdapter`
  - `OpenAICompatibleAdapter`
- 当前只统一到两条主链：
  - chat
  - embeddings

当前明确不在这一层内统一：

- stream
- tools / function calling
- vision
- file APIs

## 如何配置不同 Provider

### 1. Gemini

- `llm_provider = gemini`
- `embedding_provider = gemini`
- `api_base = https://generativelanguage.googleapis.com/v1beta`
- `llm_model` 示例：`gemini-2.5-flash`
- `embedding_model` 示例：`gemini-embedding-2-preview`

### 2. Anthropic

- `llm_provider = anthropic`
- `api_base = https://api.anthropic.com/v1`
- `model` 示例：`claude-3-5-sonnet-20241022`
- 注意：Anthropic 当前仅支持 chat，不支持 embeddings；不要把 `embedding_provider` 设为 `anthropic`

### 3. OpenAI-compatible

- `provider = openai_compatible`
- 通过 `api_base / api_key / model` 指向兼容 OpenAI 的服务
- 当前可复用到：
  - DeepSeek
  - Qwen / DashScope
  - Kimi
  - Tencent Hunyuan

### 4. 如何新增一个兼容 OpenAI 的 Provider

如果目标服务兼容 OpenAI Chat Completions 与 Embeddings：

1. 在系统设置页把 provider 设为该 alias 或 `openai_compatible`
2. 配置对应的 `api_base`
3. 填写 `api_key`
4. 填写服务支持的 `model`
5. 先执行设置页“测试连接”
6. 再做文件索引与问答联调

如果只是新增一个新的兼容 OpenAI alias，通常只需要在 `provider_adapters.py` 的 `PROVIDER_ALIASES` 中补映射，不需要改业务层。

## 测试环境部署与验收清单

建议按以下顺序执行：

1. 后端执行 `alembic upgrade head`
2. 使用 `create_admin.py` 初始化管理员
3. 启动后端
4. 启动前端
5. 登录管理员账号
6. 打开设置页，确认 `llm_provider` / `embedding_provider` 可保存并回显
7. 在设置页分别执行：
   - LLM 测试连接
   - Embedding 测试连接
8. 上传一个小 `txt` 文件并建立索引
9. 观察索引状态从 `indexing -> indexed`
10. 上传一个较大文本文件并建立索引
11. 检查大文件索引失败时是否能看到明确的限流/配额提示
12. 在 Chat 页对已索引文件提问，确认返回答案与引用
13. 切换 provider 后重新保存，并再次验证测试连接
14. 故意填入错误 key / 错误模型名 / 错误 base URL，确认错误提示清晰
15. 验证不支持能力：
    - 把 `embedding_provider` 设为 `anthropic` 时应被阻止
16. 运行：

```bash
cd apps/api
.venv\Scripts\python scripts\smoke_check.py
```

如果要覆盖主链路，再加：

```bash
set LAB_AI_KB_RUN_FULL_FLOW=1
.venv\Scripts\python scripts\smoke_check.py
```

## 常见 Provider 故障排查

- `认证失败 / AUTH_ERROR`
  - 检查 API Key
  - 检查 OpenAI Organization / Project
  - 检查 Anthropic / Gemini 是否使用了正确的原生 key

- `限流 / RATE_LIMIT / RESOURCE_EXHAUSTED`
  - 说明当前 provider 配额不足或限流
  - 可稍后重试，或调整 provider 配额与测试频率

- `模型名错误 / NOT_FOUND`
  - 检查 `model`
  - 检查 `api_base`
  - 确认 provider 与 model 是否匹配

- `参数错误 / BAD_REQUEST`
  - 检查 provider 是否选错
  - 检查是否把不支持 embeddings 的 provider 用在索引链路
  - 检查 model 是否支持当前接口

- `Anthropic 不支持 embeddings`
  - 这是当前明确限制，不是运行时故障
  - embeddings 请改用 Gemini、OpenAI 或 OpenAI-compatible provider

## 已知限制

- 当前只统一到 `chat + embeddings`
- `OpenAI-compatible` 不代表所有兼容厂商 100% 完全一致
- `OpenAI` / `Anthropic` 当前仍需真实账号做最终联调
- `stream / tools / vision` 还未统一
- 尚未建立 model-level capability 精细能力表
- 文档解析仅聚焦文本类型：`txt / md / pdf(文本型) / docx`
- 明确不支持 OCR、图像理解和多模态解析

## 最小 Smoke 检查

已提供脚本：

- `apps/api/scripts/smoke_check.py`
- `apps/api/scripts/reindex_files.py`

运行前可选设置：

```env
LAB_AI_KB_BASE_URL=http://127.0.0.1:8000
LAB_AI_KB_ADMIN_USERNAME=admin
LAB_AI_KB_ADMIN_PASSWORD=your-password
LAB_AI_KB_MEMBER_USERNAME=member
LAB_AI_KB_MEMBER_PASSWORD=your-password
LAB_AI_KB_RUN_FULL_FLOW=1
LAB_AI_KB_RUN_PROVIDER_TESTS=1
```

说明：

- 不设置 `LAB_AI_KB_RUN_FULL_FLOW=1` 时，脚本只跑权限与基础可访问性检查
- 设置为 `1` 后，脚本会继续执行最小主链路检查：
  - 上传文件
  - 提交索引任务
  - 轮询索引状态
  - 在 QA 配置完整时执行一次问答
  - 验证“已索引文件 + 未索引文件”混合作用域时仍能正常 QA
  - 验证“当前范围无 compatible indexed files”时返回简洁错误
  - 删除 smoke 会话
  - 删除 smoke 文件
- 设置 `LAB_AI_KB_RUN_PROVIDER_TESTS=1` 后，脚本会额外调用：
  - `LLM test connection`
  - `Embedding test connection`
  这要求后台已保存可用 provider 配置

执行：

```bash
cd apps/api
.venv\Scripts\python scripts\smoke_check.py
```

查看或批量重建索引：

```bash
cd apps/api
.venv\Scripts\python scripts\reindex_files.py --action report
.venv\Scripts\python scripts\reindex_files.py --action reindex-mismatch
```

脚本默认检查：

- 未登录访问 `/api/files` 返回 `401`
- `member` 访问 `/api/users` 返回 `403`
- `member` 可访问自己的 `/api/qa/sessions`
- `admin` 可访问 `/api/users`
- `admin` 可访问 `/api/settings/status`
- `member` 不可保存系统设置
- `admin` 不可读取 `member` 的会话消息

启用完整主链路检查后，还会覆盖：

- 上传文件
- 建立索引
- 问答
- 会话列表
- 删除会话
- 删除测试文件

## 前端回归清单

每次交付内部试用前，至少回归：

1. 登录后进入首页、文件页、问答页、设置页均正常
2. 未登录时访问受保护接口返回 `401`
3. `member` 看不到管理员能力，调用用户管理接口返回 `403`
4. 上传文件后文件列表能展示索引状态、索引时间、失败原因
5. 点击“建立索引/重新索引”后能进入异步索引并正确轮询状态
6. Chat 页可新建会话、切换会话、删除会话
7. 问答失败时，错误会进入会话历史且首页可见最近失败记录
8. 设置页测试 LLM / Embedding 后，首页运行状态能同步显示最近测试结果
9. 文件详情、下载、引用跳转到文件页仍正常
10. `member` 不应访问用户管理或保存系统设置

## Beta 交付前最小回归步骤

建议在内部演示或试用前按顺序执行：

1. 后端执行 `alembic upgrade head`
2. 使用 `create_admin.py` 初始化管理员
3. 启动后端和前端
4. 运行 `smoke_check.py`
5. 管理员登录并完成 LLM / Embedding 测试连接
6. 上传一个 `.txt` 或 `.md` 文件并完成索引
7. 在 Chat 页执行一次问答并检查引用来源
8. 检查首页运行状态与最近失败面板
9. 使用 `member` 账号验证权限边界

## 常见启动问题

- `数据库连接失败`
  - 检查 `DATABASE_URL`
  - 确认 PostgreSQL 已启动且目标数据库存在

- `alembic upgrade head` 失败
  - 确认 `.env` 已配置
  - 确认数据库用户有迁移权限

- 前端仍请求旧地址
  - 检查 `apps/web/.env`
  - 修改后重启 `npm run dev`

- 登录成功但接口仍返回 `401`
  - 清空浏览器本地 token 后重新登录
  - 确认后端 `JWT_SECRET_KEY` 没有在运行中被改动

- 问答不可用
  - 检查 QA 开关
  - 检查 LLM / Embedding 配置和测试结果
  - 确认目标文件已经完成索引

## 生产部署提醒

- 必须修改 `JWT_SECRET_KEY`
- 建议 PostgreSQL 与 `uploads/` 目录都做定期备份
- 建议使用反向代理统一暴露前后端服务
- 当前索引为轻量异步方案，适合内部试用和中小规模资料场景
