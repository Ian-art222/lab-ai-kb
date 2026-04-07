# eval_rag.py

Run from `apps/api` (with `.env` and database available):

```bash
python scripts/eval_rag.py --input path/to/samples.jsonl --limit 50 --output scripts/eval_rag_report.json --rerank-top-n 20
```

JSONL fields (per line): `question` (required); optional `scope_type` (default `all`), `folder_id`, `file_ids`, `strict_mode` (default false), `expected_file_ids`, `expected_chunk_ids`, `expected_keywords`.

报告中会对比 rerank off/on，并输出：

- `retrieval_file_hit_rate`
- `retrieval_chunk_hit_rate`
- `recall_at_top_k_mean`
- `mrr_at_top_k`
- `ndcg_at_top_k`
- `latency_p50_ms` / `latency_p95_ms`
- `retrieval_strategy_distribution`
- `distinct_docs_in_topk` / `distinct_docs_in_context`
- `same_doc_chunk_ratio`
- `adjacent_chunk_redundancy_rate`
- `multi_source_answer_rate`
