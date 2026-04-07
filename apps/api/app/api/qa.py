from threading import Lock
import time
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.db.session import SessionLocal, get_db
from app.models.file_record import FileRecord
from app.models.user import User
from app.services.ingest_service import ingest_file_job as run_file_ingest, resolve_index_start_status
from app.services.failure_case_service import record_failure_case
from app.services.qa_service import (
    QAServiceError,
    append_qa_failure,
    append_qa_messages,
    ask_question as run_qa,
    delete_session as remove_session,
    ensure_session,
    list_session_messages,
    list_user_sessions,
    persist_qa_citations,
    persist_retrieval_trace,
)
from app.services.reason_codes import ReasonCode
from app.services.settings_service import mark_last_qa_status
from app.schemas.qa import AskRequest, AskSuccessResponse, IngestFileRequest

router = APIRouter(prefix="/api/qa", tags=["qa"])

_active_ingest_file_ids: set[int] = set()
_active_ingest_lock = Lock()


def _map_qa_error_to_reason(code: str | None) -> str:
    mapping = {
        "NO_RELIABLE_EVIDENCE": ReasonCode.STRICT_MODE_BLOCKED.value,
        "NO_COMPATIBLE_INDEXED_CONTENT": ReasonCode.NO_RETRIEVAL_HIT.value,
        "EMBEDDING_DATA_UNAVAILABLE": ReasonCode.RETRIEVAL_FAILED.value,
        "MODEL_REQUEST_FAILED": ReasonCode.MODEL_GENERATION_FAILED.value,
    }
    return mapping.get(code or "", ReasonCode.INTERNAL_ERROR.value)


def _run_ingest_in_background(file_id: int) -> None:
    db = SessionLocal()
    try:
        file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
        if not file_record:
            return
        run_file_ingest(db, file_record, prepare_indexing=False)
    finally:
        with _active_ingest_lock:
            _active_ingest_file_ids.discard(file_id)
        db.close()


@router.post("/ask", response_model=AskSuccessResponse)
def ask_question(
    payload: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = None
    request_id = str(uuid4())
    trace_id = str(uuid4())
    started = time.perf_counter()
    try:
        session = ensure_session(
            db,
            user_id=current_user.id,
            session_id=payload.session_id,
            scope_type=payload.scope_type,
            folder_id=payload.folder_id,
        )
        result = run_qa(
            db,
            question=payload.question,
            scope_type=payload.scope_type,
            folder_id=payload.folder_id,
            file_ids=payload.file_ids,
            strict_mode=payload.strict_mode,
            top_k=payload.top_k,
            candidate_k=payload.candidate_k,
            max_context_chars=payload.max_context_chars,
            neighbor_window=payload.neighbor_window,
            dedupe_adjacent_chunks=payload.dedupe_adjacent_chunks,
            rerank_enabled=payload.rerank_enabled,
            rerank_top_n=payload.rerank_top_n,
        )
        _, assistant_message = append_qa_messages(
            db,
            session_id=session.id,
            question=payload.question,
            answer=result["answer"],
            references_json=result["references_json"],
        )
        refs = result.get("references")
        if isinstance(refs, list):
            persist_qa_citations(db, message_id=assistant_message.id, references=refs)
        meta = result.get("retrieval_meta")
        latency_ms = (time.perf_counter() - started) * 1000
        persist_retrieval_trace(
            db,
            session_id=session.id,
            assistant_message_id=assistant_message.id,
            question=payload.question,
            retrieval_meta=meta if isinstance(meta, dict) else None,
            answer_source=result.get("answer_source"),
            trace_id=trace_id,
            request_id=request_id,
            evidence_bundles=result.get("evidence_bundles") if isinstance(result.get("evidence_bundles"), dict) else None,
            latency_ms=latency_ms,
        )
        if result.get("answer_source") != "knowledge_base":
            record_failure_case(
                {
                    "trace_id": trace_id,
                    "request_id": request_id,
                    "query": payload.question,
                    "reason": (meta or {}).get("abstain_reason"),
                    "answer_source": result.get("answer_source"),
                    "references": result.get("references", []),
                    "answer_preview": (result.get("answer") or "")[:400],
                }
            )
        mark_last_qa_status(db, success=True, error_message=None)
        return {
            "session_id": session.id,
            "assistant_message_id": assistant_message.id,
            "trace_id": trace_id,
            "request_id": request_id,
            **result,
        }
    except RuntimeError as exc:
        if session is not None:
            _, assistant_message = append_qa_failure(
                db,
                session_id=session.id,
                question=payload.question,
                error_message=str(exc),
            )
            persist_retrieval_trace(
                db,
                session_id=session.id,
                assistant_message_id=assistant_message.id,
                question=payload.question,
                retrieval_meta={"failure_reason": ReasonCode.INTERNAL_ERROR.value, "is_abstained": True},
                answer_source="error",
                trace_id=trace_id,
                request_id=request_id,
                latency_ms=(time.perf_counter() - started) * 1000,
                debug_json={"message": str(exc)},
            )
            record_failure_case(
                {
                    "trace_id": trace_id,
                    "request_id": request_id,
                    "query": payload.question,
                    "reason": ReasonCode.INTERNAL_ERROR.value,
                    "answer_source": "error",
                    "references": [],
                    "answer_preview": str(exc)[:400],
                }
            )
        mark_last_qa_status(db, success=False, error_message=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except QAServiceError as exc:
        if session is not None:
            _, assistant_message = append_qa_failure(
                db,
                session_id=session.id,
                question=payload.question,
                error_message=exc.message,
                error_code=exc.code,
            )
            persist_retrieval_trace(
                db,
                session_id=session.id,
                assistant_message_id=assistant_message.id,
                question=payload.question,
                retrieval_meta={"failure_reason": _map_qa_error_to_reason(exc.code), "is_abstained": True},
                answer_source="error",
                trace_id=trace_id,
                request_id=request_id,
                latency_ms=(time.perf_counter() - started) * 1000,
                debug_json={"code": exc.code, "message": exc.message},
            )
            record_failure_case(
                {
                    "trace_id": trace_id,
                    "request_id": request_id,
                    "query": payload.question,
                    "reason": _map_qa_error_to_reason(exc.code),
                    "answer_source": "error",
                    "references": [],
                    "answer_preview": exc.message[:400],
                }
            )
        mark_last_qa_status(db, success=False, error_message=exc.message)
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post("/ingest/file")
def ingest_file(
    payload: IngestFileRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_record = db.query(FileRecord).filter(FileRecord.id == payload.file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    with _active_ingest_lock:
        already_running = payload.file_id in _active_ingest_file_ids or file_record.index_status in {
            "indexing",
            "parsing",
            "chunking",
            "embedding",
            "reindexing",
        }
        if not already_running:
            _active_ingest_file_ids.add(payload.file_id)

    if already_running:
        return {
            "file_id": file_record.id,
            "index_status": file_record.index_status,
            "indexed_at": file_record.indexed_at,
            "index_error": file_record.index_error,
            "index_warning": file_record.index_warning,
            "retry_count": file_record.retry_count,
            "last_error_code": file_record.last_error_code,
            "pipeline_version": file_record.pipeline_version,
            "queued": False,
        }

    file_record.index_status = resolve_index_start_status(
        file_record.index_status, force_reindex=payload.force_reindex
    )
    file_record.index_error = None
    file_record.index_warning = None
    file_record.indexed_at = None
    db.commit()
    db.refresh(file_record)
    background_tasks.add_task(_run_ingest_in_background, file_record.id)

    return {
        "file_id": file_record.id,
        "index_status": file_record.index_status,
        "indexed_at": file_record.indexed_at,
        "index_error": file_record.index_error,
        "index_warning": file_record.index_warning,
        "retry_count": file_record.retry_count,
        "last_error_code": file_record.last_error_code,
        "pipeline_version": file_record.pipeline_version,
        "queued": True,
    }


@router.get("/files/{file_id}/index-status")
def get_file_index_status(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    return {
        "file_id": file_record.id,
        "index_status": file_record.index_status,
        "indexed_at": file_record.indexed_at,
        "index_error": file_record.index_error,
        "index_warning": file_record.index_warning,
        "retry_count": file_record.retry_count,
        "last_error_code": file_record.last_error_code,
        "pipeline_version": file_record.pipeline_version,
    }


@router.post("/sessions")
def create_session(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = ensure_session(
        db,
        user_id=current_user.id,
        session_id=None,
        scope_type="all",
        folder_id=None,
    )
    return {"session_id": session.id}


@router.get("/sessions")
def get_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {"sessions": list_user_sessions(db, user_id=current_user.id)}


@router.get("/sessions/{session_id}/messages")
def get_session_messages(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        messages = list_session_messages(
            db,
            session_id=session_id,
            user_id=current_user.id,
        )
        return {"session_id": session_id, "messages": messages}
    except QAServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        remove_session(db, session_id=session_id, user_id=current_user.id)
        return {"message": "会话已删除"}
    except QAServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
