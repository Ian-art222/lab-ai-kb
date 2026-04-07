# Phase 2 生产治理闭环（最小实现）

## 新增能力

- 管理诊断接口：
  - `GET /api/admin/diagnostics/traces`
  - `GET /api/admin/diagnostics/traces/{trace_id}`
  - `POST /api/admin/diagnostics/files/{file_id}/retry-index?force_reindex=true|false`
- reason code 结构化：`abstain_reason` / `failure_reason` 统一枚举值。
- 失败样例沉淀：JSONL 持久化，写入失败不影响主请求。
- 索引状态扩展：`pending/parsing/chunking/embedding/indexed/failed/reindexing`。
- 预留文本型智能体扩展字段：`task_type/tool_traces_json/workflow_steps_json/session_context_json`。

## 迁移与部署

1. 执行：`cd apps/api && alembic upgrade head`
2. 回滚：`cd apps/api && alembic downgrade b1c2d3e4f5a7`

兼容性策略：
- 新增字段均为 optional 或带默认值；保留既有 `references_json` 与 `evidence_bundles` 结构。
- 诊断接口仅管理员可访问（`require_admin`）。
