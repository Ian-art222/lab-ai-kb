from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.permissions import can_view_folder, user_may_access_file_record
from app.db.session import get_db
from app.models.file_record import FileRecord
from app.models.folder import Folder
from app.models.user import User
from app.services.pdf_ingest_bridge_service import schedule_ingest
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
from app.services.settings_service import mark_last_qa_status
from app.schemas.qa import AskRequest, AskSuccessResponse, IngestFileRequest

router = APIRouter(prefix="/api/qa", tags=["qa"])

def _ensure_ask_scope(db: Session, user: User, payload: AskRequest) -> None:
    if payload.scope_type == "folder" and payload.folder_id is not None:
        folder = db.query(Folder).filter(Folder.id == payload.folder_id).first()
        if not folder or not can_view_folder(db, user, folder):
            raise HTTPException(status_code=403, detail="无权在该目录范围内问答")
    if payload.scope_type == "files" and payload.file_ids:
        for fid in payload.file_ids:
            fr = db.query(FileRecord).filter(FileRecord.id == fid).first()
            if not fr or not user_may_access_file_record(db, user, fr):
                raise HTTPException(status_code=403, detail="所选文件不可用")


@router.post("/ask", response_model=AskSuccessResponse)
def ask_question(
    payload: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = None
    try:
        _ensure_ask_scope(db, current_user, payload)
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
            session_id=session.id,
            current_user=current_user,
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
        if isinstance(meta, dict):
            meta = {
                **meta,
                "selected_evidence": result.get("references") if isinstance(result.get("references"), list) else [],
                "evidence_bundles": result.get("evidence_bundles"),
                "model_name": None,
            }
        persist_retrieval_trace(
            db,
            session_id=session.id,
            assistant_message_id=assistant_message.id,
            question=payload.question,
            retrieval_meta=meta if isinstance(meta, dict) else None,
            answer_source=result.get("answer_source"),
        )
        mark_last_qa_status(db, success=True, error_message=None)
        retrieval_meta = result.get("retrieval_meta") if isinstance(result.get("retrieval_meta"), dict) else {}
        return {
            "session_id": session.id,
            "assistant_message_id": assistant_message.id,
            **result,
            "task_type": result.get("task_type") or retrieval_meta.get("task_type"),
            "selected_skill": result.get("selected_skill") or retrieval_meta.get("selected_skill"),
            "planner_meta": result.get("planner_meta") or retrieval_meta.get("planner_meta"),
            "compare_result": result.get("compare_result") or retrieval_meta.get("compare_result"),
            "clarification_needed": (
                result.get("clarification_needed")
                if result.get("clarification_needed") is not None
                else retrieval_meta.get("clarification_needed")
            ),
            "workflow_summary": result.get("workflow_summary") or retrieval_meta.get("workflow_summary"),
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
                retrieval_meta=None,
                answer_source="error",
                debug_json={"message": str(exc), "failure_reason_code": "internal_error"},
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
                retrieval_meta=None,
                answer_source="error",
                debug_json={"code": exc.code, "message": exc.message, "failure_reason_code": "model_generation_failed"},
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
    if not user_may_access_file_record(db, current_user, file_record):
        raise HTTPException(status_code=403, detail="无权对该文件执行索引")

    result = schedule_ingest(
        db,
        file_record=file_record,
        background_tasks=background_tasks,
        reset_status=True,
    )

    db.refresh(file_record)
    return {
        "file_id": file_record.id,
        "index_status": file_record.index_status,
        "indexed_at": file_record.indexed_at,
        "index_error": file_record.index_error,
        "index_warning": file_record.index_warning,
        "queued": bool(result.get("queued")),
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
    if not user_may_access_file_record(db, current_user, file_record):
        raise HTTPException(status_code=403, detail="无权查看该文件索引状态")

    return {
        "file_id": file_record.id,
        "index_status": file_record.index_status,
        "indexed_at": file_record.indexed_at,
        "index_error": file_record.index_error,
        "index_warning": file_record.index_warning,
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
