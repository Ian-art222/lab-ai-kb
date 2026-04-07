# eval_rag.py

Run from `apps/api` (with `.env` and database available):

```bash
python scripts/eval_rag.py --input path/to/samples.jsonl --limit 50 --output scripts/eval_rag_report.json --rerank-top-n 20
```

JSONL fields (per line): `question` (required); optional `id`, `scope_type` (default `all`), `folder_id`, `file_ids`, `strict_mode` (default false), `strict` (alias of `strict_mode`), `expected_file_ids`, `expected_chunk_ids`, `expected_keywords`, `scenario_tags`, `expected_behavior`, `notes`.

Sample templates:

- `apps/api/evals/source_diversity_eval.sample.jsonl`
- `apps/api/evals/source_diversity_regression.sample.jsonl`

Recommended baseline vs optimized procedure:

1) Baseline config example:

```env
QA_DIVERSITY_RERANK_ENABLED=false
QA_MAX_CHUNKS_PER_DOC=999
QA_TARGET_DISTINCT_DOCS=1
QA_MIN_DISTINCT_DOCS_FOR_MULTI_SOURCE=1
QA_SINGLE_DOC_DOMINANCE_RATIO=999
QA_REDUNDANCY_SIM_THRESHOLD=0.999
```

2) Optimized config example:

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

3) Run eval twice (baseline first, then optimized) and compare output JSON metrics.

4) Repository boundary: this repo does **not** ship real indexed DB content; sample JSONL files are templates only. Do not fabricate baseline/optimized numeric claims without real data.

报告中会对比 rerank off/on，并输出：

- `retrieval_file_hit_rate`
- `retrieval_chunk_hit_rate`
- `recall_at_top_k_mean`
- `mrr_at_top_k`
- `ndcg_at_top_k`
- `latency_p50_ms` / `latency_p95_ms`
- `retrieval_strategy_distribution`
- `distinct_docs_in_topk_mean`
- `distinct_docs_in_context_mean`
- `same_doc_chunk_ratio_mean`
- `adjacent_chunk_redundancy_rate_mean`
- `multi_source_answer_rate`
- `citation_source_diversity_mean`
- `single_source_when_sufficient_rate`
- `unsupported_multi_source_rate`
