#!/usr/bin/env python3
"""
将 knowledge_chunks.embedding（float[]）复制到 embedding_vec（pgvector），不调用 embedding API。

适用：列已从 vector(1536) 迁到 vector(1024)，且历史子块上已有与当前 qa_pgvector_dimensions 同维的 embedding 数组
（例如此前 ingest 因维度不匹配只写了数组、未写 vec）。若更换了 embedding 模型或不确定数组来源，请改用
`scripts/reindex_files.py --action reindex-all` 全量重嵌入。

用法：
  python scripts/backfill_embedding_vec_from_array.py --dry-run
  python scripts/backfill_embedding_vec_from_array.py --batch-size 200
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.core.config import settings as app_settings
from app.db.session import SessionLocal
from app.models.knowledge import KnowledgeChunk


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只统计与打印，不写库")
    parser.add_argument("--batch-size", type=int, default=200, help="每批 commit 行数")
    args = parser.parse_args()

    dim = app_settings.qa_pgvector_dimensions
    print(f"qa_pgvector_dimensions={dim} dry_run={args.dry_run}")

    db = SessionLocal()
    try:
        q = (
            db.query(KnowledgeChunk)
            .filter(KnowledgeChunk.embedding_vec.is_(None))
            .filter(KnowledgeChunk.embedding.is_not(None))
        )
        candidates = [r for r in q.all() if isinstance(r.embedding, list) and len(r.embedding) == dim]
        print(f"candidates={len(candidates)}")
        if args.dry_run or not candidates:
            return 0

        n = 0
        for row in candidates:
            row.embedding_vec = list(row.embedding)
            n += 1
            if n % args.batch_size == 0:
                db.commit()
                print(f"committed {n}/{len(candidates)}")
        db.commit()
        print(f"done updated={n}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
