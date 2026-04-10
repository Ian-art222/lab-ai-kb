#!/usr/bin/env python3
"""Verify knowledge_chunks.embedding_vec PG type, HNSW index, and sample array lengths."""

from __future__ import annotations

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import text

from app.core.config import settings as app_settings
from app.db.session import SessionLocal


def main() -> int:
    print(f"app qa_pgvector_dimensions={app_settings.qa_pgvector_dimensions}")
    db = SessionLocal()
    try:
        col_type = db.execute(
            text(
                """
                SELECT format_type(a.atttypid, a.atttypmod) AS col_type
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                WHERE c.relname = 'knowledge_chunks'
                  AND a.attname = 'embedding_vec'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                """
            )
        ).scalar()
        print(f"PG embedding_vec column type: {col_type or '<missing>'}")

        rows = db.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = 'knowledge_chunks'
                  AND indexdef ILIKE '%embedding_vec%'
                ORDER BY indexname
                """
            )
        ).fetchall()
        print("Indexes mentioning embedding_vec:")
        for name, idef in rows:
            print(f"  - {name}: {idef}")

        n_vec = db.execute(
            text("SELECT COUNT(*) FROM knowledge_chunks WHERE embedding_vec IS NOT NULL")
        ).scalar()
        n_emb = db.execute(
            text(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NOT NULL "
                "AND cardinality(embedding) > 0"
            )
        ).scalar()
        print(f"Rows: embedding_vec NOT NULL={n_vec}, embedding array non-empty={n_emb}")

        samp = db.execute(
            text(
                """
                SELECT id, cardinality(embedding) AS emb_len
                FROM knowledge_chunks
                WHERE embedding IS NOT NULL AND cardinality(embedding) > 0
                ORDER BY id
                LIMIT 5
                """
            )
        ).fetchall()
        print("Sample embedding cardinalities (first 5 rows):", samp)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
