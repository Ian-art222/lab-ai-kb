from __future__ import annotations

import argparse
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.db.session import SessionLocal
from app.models.file_record import FileRecord
from app.services.ingest_service import ingest_file_job
from app.services.settings_service import build_embedding_index_standard, get_or_create_settings


def classify_file(file_record: FileRecord, current_index_standard: str) -> str:
    file_standard = build_embedding_index_standard(
        embedding_provider=file_record.index_embedding_provider,
        embedding_model=file_record.index_embedding_model,
    )
    if file_record.index_status != "indexed":
        return "needs_index"
    if not file_standard:
        return "legacy_index_missing_metadata"
    if file_standard != current_index_standard:
        return "needs_reindex"
    if file_record.index_embedding_dimension is None:
        return "needs_reindex"
    return "compatible"


def print_report(files: list[FileRecord], *, current_index_standard: str) -> dict[str, list[FileRecord]]:
    buckets: dict[str, list[FileRecord]] = {
        "compatible": [],
        "needs_index": [],
        "needs_reindex": [],
        "legacy_index_missing_metadata": [],
    }
    for file_record in files:
        buckets.setdefault(classify_file(file_record, current_index_standard), []).append(file_record)

    print(f"Current retrieval index standard: {current_index_standard or '<not configured>'}")
    for key in ("compatible", "needs_index", "needs_reindex", "legacy_index_missing_metadata"):
        print(f"- {key}: {len(buckets[key])}")
    print()

    for key in ("needs_index", "needs_reindex", "legacy_index_missing_metadata"):
        if not buckets[key]:
            continue
        print(f"[{key}]")
        for file_record in buckets[key]:
            file_standard = build_embedding_index_standard(
                embedding_provider=file_record.index_embedding_provider,
                embedding_model=file_record.index_embedding_model,
            )
            print(
                f"  id={file_record.id} status={file_record.index_status} "
                f"standard={file_standard or '<none>'} dim={file_record.index_embedding_dimension} "
                f"name={file_record.file_name}"
            )
        print()
    return buckets


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report or rebuild file indexes using the current retrieval embedding standard."
    )
    parser.add_argument(
        "--action",
        choices=("report", "reindex-mismatch", "reindex-all"),
        default="report",
        help="report only, rebuild mismatched/legacy indexes, or rebuild all uploaded files",
    )
    parser.add_argument(
        "--file-id",
        dest="file_ids",
        type=int,
        action="append",
        default=[],
        help="limit operation to one or more file IDs",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        settings = get_or_create_settings(db)
        current_index_standard = build_embedding_index_standard(
            embedding_provider=settings.embedding_provider,
            embedding_model=settings.embedding_model,
        )
        if not current_index_standard:
            print("Retrieval embedding is not fully configured. Configure embedding_provider/model first.")
            return 1

        query = db.query(FileRecord).order_by(FileRecord.id.asc())
        if args.file_ids:
            query = query.filter(FileRecord.id.in_(args.file_ids))
        files = query.all()
        buckets = print_report(files, current_index_standard=current_index_standard)

        if args.action == "report":
            return 0

        if args.action == "reindex-mismatch":
            targets = buckets["needs_reindex"] + buckets["legacy_index_missing_metadata"]
        else:
            targets = files

        if not targets:
            print("No files need reindexing for the selected action.")
            return 0

        print(f"Reindex target count: {len(targets)}")
        for file_record in targets:
            print(f"Reindexing file id={file_record.id} name={file_record.file_name}")
            result = ingest_file_job(db, file_record, prepare_indexing=True)
            print(
                f"  -> status={result.index_status} warning={result.index_warning or '-'} "
                f"error={result.index_error or '-'}"
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
