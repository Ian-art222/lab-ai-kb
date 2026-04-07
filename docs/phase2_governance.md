# Phase 2 生产治理闭环说明

## 已落地能力

1. **Trace 查询诊断 API（管理员）**
   - `GET /api/admin/diagnostics/traces`
   - `GET /api/admin/diagnostics/traces/{trace_id}`
   - 支持按 `trace_id/request_id/session_id/时间/abstained/failed` 查询。

2. **结构化拒答/失败原因**
   - 统一 reason code：`no_retrieval_hit`、`low_retrieval_confidence`、`strict_mode_blocked`、`model_generation_failed`、`internal_error` 等。
   - `retrieval_meta` 与 trace 持久化同步记录机器可读原因。

3. **评测与回归**
   - 新增 `evals/` 标准目录与 `evals/runners/run_phase2_eval.py`。
   - 支持输出 JSON/Markdown 报告和失败样例 JSONL。

4. **失败样例沉淀**
   - 在线问答遇到 abstain / error 自动写入 `evals/reports/failure_cases.jsonl`。

5. **索引状态机与重试增强**
   - 细化状态：`parsing/chunking/embedding/reindexing/indexed/failed`。
   - `files` 增加 `retry_count`、`last_error_code`、`pipeline_version`。
   - 管理接口支持重试重建索引。

## 回滚策略（最小）

- 关闭管理路由不影响核心问答。
- 评测与失败样例为旁路能力，可独立停用。
- 若需回滚数据库字段，执行 alembic downgrade 到上一版本。

