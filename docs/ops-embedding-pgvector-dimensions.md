# pgvector 维度与智谱 Embedding-3

## 关键事实

1. **智谱 Embedding-3** 不传 `dimensions` 时，API 默认返回 **2048** 维（见智谱文档）。
2. **pgvector HNSW** 在 PostgreSQL 中要求 **索引列维度 ≤ 2000**，因此 **不能** 对 `vector(2048)` 创建 HNSW（会报 `column cannot have more than 2000 dimensions for hnsw index`）。
3. 本项目当前迁移将 `embedding_vec` 固定为 **`vector(1024)`**，与 **`QA_PGVECTOR_DIMENSIONS=1024`**、ORM `Vector(1024)` 一致。

## 推荐配置（DeepSeek 聊天 + 智谱向量）

- **聊天**：`system_settings` / 环境变量中 `llm_*` → DeepSeek OpenAI 兼容网关（如 `https://api.deepseek.com`）。
- **向量**：`embedding_*` → 智谱 `https://open.bigmodel.cn/api/paas/v4`，模型 `embedding-3`（或 `Embedding-3`）。
- **固定 1024 维输出**（二选一或同时）：
  1. 在 **`EMBEDDING_EXTRA_PARAMS_JSON`**（`apps/api/.env`）中设置 `{"dimensions":1024}`；或  
  2. 依赖 **`model_service._resolve_embedding_extra_params`**：当 `embedding_api_base` 含 `bigmodel.cn` 且模型名为 **`embedding-3`**（大小写不敏感）且未显式传 `dimensions` 时，自动使用 **`qa_pgvector_dimensions`** 作为请求体中的 `dimensions`，使 API 返回长度与 `vector(N)` 一致。  
  启动日志中的 **QA embedding probe** 会校验实际返回长度。

若改用其他 `dimensions`（如 512），须：**新 Alembic 迁移改 `vector(N)` + 改 `qa_pgvector_dimensions` + 全量 reindex**。

## 回填 vs 全量 reindex

- 历史 `embedding` 数组已是 **1024** 且与当前模型/参数一致，仅 `embedding_vec` 空：可 `backfill_embedding_vec_from_array.py`。
- 曾为 **2048** 或未传 `dimensions` 写入的数组与当前 **1024** 列不一致：**必须** `reindex_files.py --action reindex-all`。
