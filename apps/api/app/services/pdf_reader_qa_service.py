from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.file_record import FileRecord
from app.models.user import User
from app.services.qa_service import ask_question


def ask_in_pdf(
    db: Session,
    *,
    file_record: FileRecord,
    question: str,
    current_user: User,
    strict_mode: bool = True,
    top_k: int = 6,
) -> dict:
    result = ask_question(
        db,
        question=question,
        scope_type="files",
        folder_id=None,
        file_ids=[file_record.id],
        strict_mode=strict_mode,
        top_k=top_k,
        session_id=None,
        current_user=current_user,
    )
    return {
        "answer": result.get("answer", ""),
        "references": result.get("references", []),
        "answer_source": result.get("answer_source"),
        "retrieval_meta": result.get("retrieval_meta", {}),
        "used_files": result.get("used_files", [file_record.id]),
    }
