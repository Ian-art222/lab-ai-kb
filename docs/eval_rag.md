# eval_rag.py

Run from `apps/api` (with `.env` and database available):

```bash
python scripts/eval_rag.py --input path/to/samples.jsonl --limit 50 --output scripts/eval_rag_report.json --rerank-top-n 20
```

JSONL fields (per line): `question` (required); optional `scope_type` (default `all`), `folder_id`, `file_ids`, `strict_mode` (default false), `expected_file_ids`, `expected_chunk_ids`, `expected_keywords`.

## Diversity-related metrics

The report now includes retrieval/context metrics for document diversity:

- `distinct_docs_in_topk`
- `distinct_docs_in_context`
- `same_doc_chunk_ratio`
- `adjacent_chunk_redundancy_rate`
- `multi_source_answer_rate`

Interpretation:
- We do **not** force multi-source answers.
- A healthy result usually has lower `same_doc_chunk_ratio` and lower `adjacent_chunk_redundancy_rate`,
  while preserving hit/recall quality.
