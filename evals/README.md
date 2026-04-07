# Evals（Phase 2）

目录结构：

- `datasets/`：评测问题与期望行为
- `fixtures/`：可重复运行的预测样例
- `runners/`：评测执行脚本
- `reports/`：输出报告与失败样例沉淀

## 快速运行

```bash
python evals/runners/run_phase2_eval.py
```

输出：
- `evals/reports/phase2_eval_report.json`
- `evals/reports/phase2_eval_report.md`
- `evals/reports/phase2_failure_cases.jsonl`

说明：
- 当前 runner 是可重复基线版本，不依赖线上人工操作。
- 后续可把 `fixtures` 替换为真实系统批量推理结果，并扩展 judge 指标。

