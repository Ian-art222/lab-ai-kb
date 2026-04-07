# eval_rag.py

Run from `apps/api` (with `.env` and database available):

```bash
python scripts/eval_rag.py --input path/to/samples.jsonl --limit 50 --output scripts/eval_rag_report.json --rerank-top-n 20
```

JSONL fields (per line): `question` (required); optional `scope_type` (default `all`), `folder_id`, `file_ids`, `strict_mode` (default false), `expected_file_ids`, `expected_chunk_ids`, `expected_keywords`.
