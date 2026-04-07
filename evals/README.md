# Evals (Phase 2)

目录约定：

- `datasets/`: 可重复回归数据集（JSONL）
- `fixtures/`: 失败样例沉淀目录（默认由 API 写入）
- `runners/`: 命令行 runner
- `reports/`: 报告输出目录（JSON / Markdown / failures.jsonl）

## 运行

```bash
python evals/runners/run_phase2_eval.py \
  --dataset evals/datasets/phase2_regression_sample.jsonl \
  --out-json evals/reports/phase2_report.json \
  --out-md evals/reports/phase2_report.md \
  --out-failures evals/reports/phase2_failures.jsonl
```

## 失败样例回流

应用运行时会把失败样例写入 `evals/fixtures/failure_cases/qa_failure_cases.jsonl`（可通过 `QA_FAILURE_CASES_DIR` 配置覆盖）。
可将该 JSONL 直接并入 `datasets/` 做后续回归。

## Phase 3A 受控文本智能体评测（最小版）

```bash
python evals/runners/run_phase3_eval.py \
  --dataset evals/datasets/phase3_agent_eval_sample.jsonl \
  --out-json evals/reports/phase3_report.json \
  --out-md evals/reports/phase3_report.md \
  --out-failures evals/reports/phase3_failures.jsonl
```

新增报告字段包括：`task_type`、`planner_strategy`、`predicted_answer`、`citations_count`、`multi_source_coverage`、`abstained`、`reason_code`、`compare_structure_quality`。
