# Phase 0 审计与 Phase 1 改造计划（2026-04-07）

## 1) 现状结论（基于代码审计）
- 后端：FastAPI + SQLAlchemy + Alembic + PostgreSQL/pgvector；前端：Vue3 + Element Plus。  
- 已具备：文件上传下载、目录管理、基础索引状态、hybrid retrieval、rerank、引用落库、基础 retrieval trace。  
- 主要不足：chunk 元数据不够结构化、证据组装以片段列表为主、缺少 abstain 原因结构化字段、评测闭环仍偏脚本化。

## 2) Phase 1 目标（P0）
1. 结构化解析与元数据保真增强（含 CSV/TSV）。
2. 多来源 evidence assembly（按来源聚合 primary/supplementary）。
3. retrieval_meta 增强（normalized query / rewritten queries / abstain reason）。
4. 保持 API 兼容：扩展字段优先、默认不破坏已有调用方。

## 3) 兼容性策略
- `references_json` 保持原有结构（仍为引用片段列表）；新增证据聚合通过独立 `evidence_bundles` 字段提供。
- retrieval_meta 新字段全部为 optional。
- 数据库 schema 本轮不新增列，优先利用 `metadata_json` 承载可追溯字段。

## 4) 后续阶段（摘要）
- Phase 2：索引状态机扩展、trace 管理接口、评测自动化回归。
- Phase 3：受控 agent orchestrator（白名单工具 + 状态机 + trace）。
- Phase 4：灰度、性能、成本与发布流程打磨。

## 5) Phase 2 本次落地补充
- 新增管理诊断 API：按 `trace_id` / `request_id` / `session_id` / 时间范围查询 trace。
- trace 增强字段：`abstain_reason` / `failure_reason` / `is_abstained` / `latency_ms` / `evidence_bundles_json` 等。
- 新增 `evals/` 标准目录与可重复 runner，输出 JSON/Markdown 报告与失败样例 JSONL。
- 索引治理增强：`files.retry_count`、`files.last_error_code`、`files.pipeline_version`，并补充状态流转（`parsing/chunking/embedding/reindexing`）。
