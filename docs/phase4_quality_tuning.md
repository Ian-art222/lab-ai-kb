# Phase 4: RAG Agent 质量跃迁（调参说明）

## 本轮策略阈值（集中在后端 `qa_service.py`）

- compare：`min_source_count=2`，`max_dominant_source_ratio=0.65`，`min_multi_source_coverage=0.67`。
- synthesis：`min_source_count=2`，`max_dominant_source_ratio=0.72`，`min_multi_source_coverage=0.67`。
- default QA：`min_source_count=1`，`max_dominant_source_ratio=0.82`，`min_multi_source_coverage=0.34`。

## 当前启发式规则

1. **compare target 抽取**：优先识别“比较/对比 + A/B 连接词（和/与/vs/versus）”；对象不明确时路由到 clarify。  
2. **coverage 策略驱动**：coverage 不足可触发 fallback；fallback 后仍不足则保守或 abstain。  
3. **compare 对称性策略**：比较结果输出 `evidence_symmetry` / `evidence_asymmetry`，不允许单侧证据直接推导双侧结论。  
4. **guardrail 三层**：input / evidence / output guardrail 统一进入 `tool_traces`，并可在 diagnostics 中聚合查看。  

## Eval 如何用于调参

- 先跑 `evals/runners/run_phase3_eval.py`（Phase4 规则已内联升级）。
- 关注失败样例中：
  - `dominance_not_handled`
  - `compare_asymmetry_not_flagged`
  - `clarification_boundary_mismatch`
- 若 compare 误触发 clarify 偏多：放宽 compare target 抽取正则。  
- 若单源倾斜漏报：收紧 `max_dominant_source_ratio`。  
- 若误拒答偏多：放宽 `min_multi_source_coverage`，但保持 guardrail 提示。

## 后续优先调优点

- compare 多侧目标（>2）的稳健降级策略。
- fallback 第二轮 query 重写质量。
- output guardrail 对“无引用强结论”的细粒度检测。
