# feat(rag): source diversity control 验证闭环与文档交付增强

## 背景
当前云端知识库 / 文本型 RAG 项目已完成 source diversity control 主链路优化（doc-aware selection、dominance guardrail、adjacent redundancy suppression、diversity rerank 等）。本轮不再改检索主链路，只做验证闭环与交付文档补全。

## 问题
之前缺少可直接运行的评测样例模板与统一验证说明，导致回归测试依赖口头约定，不利于稳定复现“同文档 chunk 霸榜”问题与优化收益。

## 目标
1. 提供可直接运行的评测样例（通用集 + 回归专项集）。
2. 在 README 中补齐 source diversity control 的设计原则、配置解释与 baseline/optimized 跑法。
3. 产出可直接复用的 PR 文案模板，便于后续提交。

## 主要改动
- 新增 `apps/api/evals/source_diversity_eval.sample.jsonl`：覆盖 5 类场景
  - `single-source-sufficient`
  - `multi-source-complementary`
  - `long-doc-dominance`
  - `adjacent-chunk-overlap`
  - `should-refuse`
- 新增 `apps/api/evals/source_diversity_regression.sample.jsonl`：聚焦 source diversity control 回归题。
- 更新 `README.md`：新增“Source Diversity Control（工程说明 + 验证跑法）”章节，包含：
  - 机制与边界说明
  - 关键配置项解释
  - baseline / optimized 示例配置
  - eval 执行命令与重点指标
  - 无真实已索引数据时的诚实披露要求
- 对 `apps/api/scripts/eval_rag.py` 做最小兼容：样例支持 `strict`（别名）并保留 `strict_mode`，同时允许承载 `id / expected_behavior / notes` 元数据。

## 为什么这样设计
- 保持最小增量：不触碰 retrieval / rerank / context assembly 主逻辑。
- 样例与脚本轻兼容：避免新增一套脚本或破坏现有字段。
- 文档直达执行：让评估与回归可以“拿来即跑”，降低维护成本。

## 风险
- 样例模板并不等于真实评测结果；若无真实索引库，不能据此下性能或质量结论。
- baseline/optimized 参数在不同知识库上可能需要再调优。

## 验证方式
1. JSONL 语法检查（逐行 JSON 解析）。
2. `eval_rag.py` 命令行可执行性检查（`--help`）。
3. 若改动 Python，执行 `py_compile`。

## 成功标准（明确）
本轮成功标准不是强制多文档引用，而是：
- 单文档足够时依然稳定。
- 多文档互补时能自然融合。
- 同一篇文档多个相邻 chunk 占满 context 的现象显著减少。
- 最终答案质量不因多样性策略明显退化。

## 后续优化方向
- 基于真实已索引数据执行 baseline vs optimized 对比并沉淀参数建议。
- 增加分场景阈值建议（例如 long-doc 与 should-refuse 场景分离调参）。
- 将回归样例纳入 CI（可在有测试数据环境时启用）。
