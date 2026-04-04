from __future__ import annotations

import math
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.file_record import FileRecord
from app.models.folder import Folder
from app.models.knowledge import KnowledgeChunk, QAMessage, QASession
from app.models.system_setting import SystemSetting
from app.services.model_service import chat_completion, embed_texts
from app.services.settings_service import build_embedding_index_standard

MIN_SIMILARITY_SCORE = 0.25
MAX_TOP_K = 8
MIN_TOP_K = 1
MIN_RETRIEVAL_CHUNK_CHARS = 60
SNIPPET_TRUNCATE_LENGTH = 220


class QAServiceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def ensure_session(
    db: Session,
    *,
    user_id: int,
    session_id: int | None,
    scope_type: str,
    folder_id: int | None,
) -> QASession:
    if session_id is not None:
        session = (
            db.query(QASession)
            .filter(QASession.id == session_id, QASession.user_id == user_id)
            .first()
        )
        if session:
            session.scope_type = scope_type
            session.folder_id = folder_id
            session.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(session)
            return session

    session = QASession(
        user_id=user_id,
        title=None,
        scope_type=scope_type,
        folder_id=folder_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def append_qa_messages(
    db: Session,
    *,
    session_id: int,
    question: str,
    answer: str,
    references: list[dict],
) -> tuple[QAMessage, QAMessage]:
    now = datetime.utcnow()
    user_message = QAMessage(
        session_id=session_id,
        role="user",
        content=question,
        references_json=None,
        created_at=now,
    )
    assistant_message = QAMessage(
        session_id=session_id,
        role="assistant",
        content=answer,
        references_json=references,
        created_at=now,
    )
    db.add(user_message)
    db.add(assistant_message)
    session = db.query(QASession).filter(QASession.id == session_id).first()
    if session:
        if not session.title:
            session.title = question[:80]
        session.updated_at = now
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)
    return user_message, assistant_message


def append_qa_failure(
    db: Session,
    *,
    session_id: int,
    question: str,
    error_message: str,
    error_code: str | None = None,
) -> tuple[QAMessage, QAMessage]:
    now = datetime.utcnow()
    user_message = QAMessage(
        session_id=session_id,
        role="user",
        content=question,
        references_json=None,
        created_at=now,
    )
    assistant_message = QAMessage(
        session_id=session_id,
        role="assistant",
        content=error_message,
        references_json={"kind": "error", "code": error_code} if error_code else {"kind": "error"},
        created_at=now,
    )
    db.add(user_message)
    db.add(assistant_message)
    session = db.query(QASession).filter(QASession.id == session_id).first()
    if session:
        if not session.title:
            session.title = question[:80]
        session.updated_at = now
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)
    return user_message, assistant_message


def list_session_messages(
    db: Session,
    *,
    session_id: int,
    user_id: int,
) -> list[dict]:
    session = (
        db.query(QASession)
        .filter(QASession.id == session_id, QASession.user_id == user_id)
        .first()
    )
    if not session:
        raise QAServiceError("SESSION_NOT_FOUND", "问答会话不存在")

    rows = (
        db.query(QAMessage)
        .filter(QAMessage.session_id == session_id)
        .order_by(QAMessage.created_at.asc(), QAMessage.id.asc())
        .all()
    )
    return [
        {
            "id": row.id,
            "session_id": row.session_id,
            "role": row.role,
            "content": row.content,
            "references_json": row.references_json,
            "state": (
                "error"
                if row.role == "assistant"
                and isinstance(row.references_json, dict)
                and row.references_json.get("kind") == "error"
                else "normal"
            ),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def list_user_sessions(
    db: Session,
    *,
    user_id: int,
) -> list[dict]:
    sessions = (
        db.query(QASession)
        .filter(QASession.user_id == user_id)
        .order_by(QASession.updated_at.desc(), QASession.id.desc())
        .all()
    )
    items: list[dict] = []
    for session in sessions:
        last_user_message = (
            db.query(QAMessage)
            .filter(QAMessage.session_id == session.id, QAMessage.role == "user")
            .order_by(QAMessage.created_at.desc(), QAMessage.id.desc())
            .first()
        )
        last_assistant_message = (
            db.query(QAMessage)
            .filter(QAMessage.session_id == session.id, QAMessage.role == "assistant")
            .order_by(QAMessage.created_at.desc(), QAMessage.id.desc())
            .first()
        )
        message_count = (
            db.query(QAMessage).filter(QAMessage.session_id == session.id).count()
        )
        last_error = None
        if last_assistant_message and isinstance(last_assistant_message.references_json, dict):
            if last_assistant_message.references_json.get("kind") == "error":
                last_error = last_assistant_message.content
        items.append(
            {
                "id": session.id,
                "title": session.title or (last_user_message.content[:80] if last_user_message else "新会话"),
                "scope_type": session.scope_type,
                "folder_id": session.folder_id,
                "last_question": last_user_message.content if last_user_message else None,
                "last_error": last_error,
                "message_count": message_count,
                "updated_at": session.updated_at.isoformat(),
                "created_at": session.created_at.isoformat(),
            }
        )
    return items


def delete_session(
    db: Session,
    *,
    session_id: int,
    user_id: int,
) -> None:
    session = (
        db.query(QASession)
        .filter(QASession.id == session_id, QASession.user_id == user_id)
        .first()
    )
    if not session:
        raise QAServiceError("SESSION_NOT_FOUND", "问答会话不存在")
    db.delete(session)
    db.commit()


def _build_snippet(text: str, limit: int = SNIPPET_TRUNCATE_LENGTH) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}..."


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _get_descendant_ids(db: Session, folder_id: int) -> set[int]:
    descendant_ids: set[int] = set()
    queue: list[int] = [folder_id]
    while queue:
        current_id = queue.pop()
        children = db.query(Folder).filter(Folder.parent_id == current_id).all()
        for child in children:
            if child.id in descendant_ids:
                continue
            descendant_ids.add(child.id)
            queue.append(child.id)
    return descendant_ids


def _load_settings(db: Session) -> SystemSetting:
    settings = db.query(SystemSetting).filter(SystemSetting.id == 1).first()
    if not settings:
        raise QAServiceError("SETTINGS_NOT_FOUND", "系统设置不存在")
    return settings


def _list_files_in_scope(
    db: Session,
    *,
    scope_type: str,
    folder_id: int | None,
    file_ids: list[int] | None,
) -> list[FileRecord]:
    query = db.query(FileRecord)
    if scope_type == "folder" and folder_id is not None:
        scope_folder_ids = {folder_id, *_get_descendant_ids(db, folder_id)}
        query = query.filter(FileRecord.folder_id.in_(scope_folder_ids))
    elif scope_type == "files":
        if not file_ids:
            return []
        query = query.filter(FileRecord.id.in_(file_ids))
    return query.order_by(FileRecord.id.asc()).all()


def _collect_retrievable_file_ids(
    db: Session,
    *,
    settings: SystemSetting,
    scope_type: str,
    folder_id: int | None,
    file_ids: list[int] | None,
    expected_dimension: int | None,
) -> list[int]:
    current_standard = build_embedding_index_standard(
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
    )
    if not current_standard:
        return []

    scoped_files = _list_files_in_scope(
        db,
        scope_type=scope_type,
        folder_id=folder_id,
        file_ids=file_ids,
    )
    compatible_indexed_file_ids: list[int] = []
    for file_record in scoped_files:
        if file_record.index_status != "indexed":
            continue
        file_standard = build_embedding_index_standard(
            embedding_provider=file_record.index_embedding_provider,
            embedding_model=file_record.index_embedding_model,
        )
        if file_standard != current_standard:
            continue
        if expected_dimension is not None and file_record.index_embedding_dimension != expected_dimension:
            continue
        compatible_indexed_file_ids.append(file_record.id)

    if not compatible_indexed_file_ids:
        return []

    retrievable_ids = (
        db.query(KnowledgeChunk.file_id)
        .filter(KnowledgeChunk.file_id.in_(compatible_indexed_file_ids))
        .filter(KnowledgeChunk.embedding.is_not(None))
        .filter(KnowledgeChunk.token_count.is_not(None))
        .filter(KnowledgeChunk.token_count >= MIN_RETRIEVAL_CHUNK_CHARS)
        .distinct()
        .all()
    )
    return [file_id for (file_id,) in retrievable_ids]


def _retrieve_chunks(
    db: Session,
    *,
    query_embedding: list[float],
    compatible_file_ids: list[int],
    top_k: int,
) -> list[dict]:
    top_k = max(MIN_TOP_K, min(top_k, MAX_TOP_K))
    expected_dimension = len(query_embedding)
    if expected_dimension == 0:
        raise QAServiceError("EMBEDDING_DATA_UNAVAILABLE", "查询向量为空，无法执行检索")
    if not compatible_file_ids:
        return []

    query = (
        db.query(KnowledgeChunk, FileRecord.file_name, FileRecord.folder_id)
        .join(FileRecord, KnowledgeChunk.file_id == FileRecord.id)
        .filter(KnowledgeChunk.file_id.in_(compatible_file_ids))
        .filter(KnowledgeChunk.embedding.is_not(None))
        .filter(KnowledgeChunk.token_count.is_not(None))
        .filter(KnowledgeChunk.token_count >= MIN_RETRIEVAL_CHUNK_CHARS)
    )

    candidates = query.all()
    ranked: list[dict] = []
    for chunk, file_name, chunk_folder_id in candidates:
        embedding = chunk.embedding or []
        if not embedding:
            continue
        if len(embedding) != expected_dimension:
            raise QAServiceError(
                "EMBEDDING_DIMENSION_MISMATCH",
                "当前索引数据的 embedding 维度不一致，请重新索引相关文件",
            )
        if not chunk.content.strip() or (chunk.token_count or 0) < MIN_RETRIEVAL_CHUNK_CHARS:
            continue
        score = _cosine_similarity(query_embedding, embedding)
        ranked.append(
            {
                "chunk": chunk,
                "file_name": file_name,
                "folder_id": chunk_folder_id,
                "score": score,
            }
        )

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:top_k]

def ask_question(
    db: Session,
    *,
    question: str,
    scope_type: str,
    folder_id: int | None,
    file_ids: list[int] | None,
    strict_mode: bool,
    top_k: int,
) -> dict:
    if scope_type == "files" and not file_ids:
        raise QAServiceError("NO_INDEXED_CONTENT", "当前尚未选择文件范围，请先选择至少一个文件")

    settings = _load_settings(db)
    if not settings.qa_enabled:
        raise QAServiceError("QA_DISABLED", "智能问答尚未启用")
    if not (
        settings.embedding_provider
        and settings.embedding_api_base
        and settings.embedding_api_key
        and settings.embedding_model
    ):
        raise QAServiceError("EMBEDDING_NOT_CONFIGURED", "Embedding 配置不完整，无法执行问答")
    if not (settings.llm_provider and settings.llm_api_base and settings.llm_api_key and settings.llm_model):
        raise QAServiceError("LLM_NOT_CONFIGURED", "LLM 配置不完整，无法执行问答")

    top_k = max(MIN_TOP_K, min(top_k, MAX_TOP_K))

    try:
        query_embedding = embed_texts(
            provider=settings.embedding_provider,
            api_base=settings.embedding_api_base,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            inputs=[question],
            embedding_batch_size_from_db=settings.embedding_batch_size,
        )[0]
    except RuntimeError as exc:
        raise QAServiceError("MODEL_REQUEST_FAILED", "模型服务请求失败，请检查当前配置与连接状态") from exc

    compatible_file_ids = _collect_retrievable_file_ids(
        db,
        settings=settings,
        scope_type=scope_type,
        folder_id=folder_id,
        file_ids=file_ids,
        expected_dimension=len(query_embedding),
    )
    if not compatible_file_ids:
        raise QAServiceError(
            "NO_COMPATIBLE_INDEXED_CONTENT",
            "当前范围内没有可用于当前知识库索引标准的已索引文献，请先建立或重建索引。",
        )

    matches = _retrieve_chunks(
        db,
        query_embedding=query_embedding,
        compatible_file_ids=compatible_file_ids,
        top_k=top_k,
    )

    if not matches:
        raise QAServiceError("NO_RELIABLE_EVIDENCE", "未检索到足够可靠的依据，当前问题暂时无法回答")

    reliable_matches = [item for item in matches if item["score"] >= MIN_SIMILARITY_SCORE]
    if strict_mode and not reliable_matches:
        raise QAServiceError("NO_RELIABLE_EVIDENCE", "未检索到足够可靠的依据，当前问题暂时无法回答")

    final_matches = reliable_matches or matches[: min(3, len(matches))]
    context_blocks = []
    references = []
    used_files: list[int] = []
    for item in final_matches:
        chunk = item["chunk"]
        context_blocks.append(
            f"[文件: {item['file_name']} | chunk: {chunk.chunk_index}]\n{chunk.content}"
        )
        references.append(
            {
                "file_id": chunk.file_id,
                "file_name": item["file_name"],
                "chunk_id": chunk.id,
                "chunk_index": chunk.chunk_index,
                "snippet": _build_snippet(chunk.content),
                "score": item["score"],
                "section_title": chunk.section_title,
                "page_number": chunk.page_number,
            }
        )
        if chunk.file_id not in used_files:
            used_files.append(chunk.file_id)

    prompt = (
        "你是实验室内部知识库问答助手。请严格依据提供的资料片段回答问题。"
        "如果资料不足以支撑结论，请明确说“无法根据现有资料确认”。\n\n"
        f"问题：{question}\n\n"
        "资料片段：\n"
        + "\n\n".join(context_blocks)
    )

    try:
        answer = chat_completion(
            provider=settings.llm_provider,
            api_base=settings.llm_api_base,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个谨慎、可追溯的实验室知识问答助手。",
                },
                {"role": "user", "content": prompt},
            ],
        )
    except RuntimeError as exc:
        raise QAServiceError("MODEL_REQUEST_FAILED", "模型服务请求失败，请检查当前配置与连接状态") from exc

    return {
        "answer": answer,
        "references": references,
        "used_files": used_files,
        "retrieval_meta": {
            "scope_type": scope_type,
            "top_k": top_k,
            "min_score": MIN_SIMILARITY_SCORE,
            "candidate_chunks": len(matches),
            "matched_chunks": len(final_matches),
        },
    }
