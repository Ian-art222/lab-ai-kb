from __future__ import annotations

import logging
import math
import re
import time
from datetime import datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.models.file_record import FileRecord
from app.models.folder import Folder
from app.models.knowledge import KnowledgeChunk, QACitation, QAMessage, QARetrievalTrace, QASession
from app.models.system_setting import SystemSetting
from app.services.model_service import chat_completion, embed_texts
from app.services.settings_service import build_embedding_index_standard

MIN_SIMILARITY_SCORE = 0.25
MIN_HYBRID_RRF_SCORE = 0.012
MAX_TOP_K = 8
MIN_TOP_K = 1
MIN_RETRIEVAL_CHUNK_CHARS = 60
SNIPPET_TRUNCATE_LENGTH = 220

logger = logging.getLogger(__name__)

DEFAULT_RETRIEVAL_STRATEGY = "app_layer_cosine_topk"

# Upper bound for in-memory ranked pool (top_k vs qa_candidate_k); avoids unbounded scans.
QA_RETRIEVAL_POOL_CAP = 128


def _normalize_retrieval_mode(value: str | None) -> str:
    mode = (value or "").strip().lower()
    if mode in {"semantic", "lexical", "hybrid"}:
        return mode
    return "hybrid"


def _score_threshold_for_mode(mode: str) -> float:
    if mode == "semantic":
        return float(app_settings.qa_semantic_threshold)
    if mode == "lexical":
        return float(app_settings.qa_lexical_threshold)
    return float(app_settings.qa_hybrid_threshold)


def _build_query_variants(question: str) -> list[str]:
    base = " ".join((question or "").split()).strip()
    if not base:
        return []
    if not app_settings.qa_query_expansion_enabled:
        return [base]

    variants: list[str] = [base]
    compact = re.sub(r"[^\w\u4e00-\u9fff]+", " ", base, flags=re.UNICODE).strip()
    if compact and compact != base:
        variants.append(compact)

    # Keep high-signal words as a lexical-biased variant.
    tokens = [tok for tok in compact.split() if len(tok) >= 2]
    if len(tokens) >= 3:
        variants.append(" ".join(tokens[:12]))

    max_q = max(1, int(app_settings.qa_query_expansion_max_queries))
    out: list[str] = []
    seen: set[str] = set()
    for q in variants:
        nq = q.strip()
        if not nq or nq in seen:
            continue
        seen.add(nq)
        out.append(nq)
        if len(out) >= max_q:
            break
    return out or [base]


def _child_or_legacy_retrieval_filter():
    """Recall child rows; NULL chunk_kind keeps legacy chunks indexed before parent-child."""
    return or_(KnowledgeChunk.chunk_kind == "child", KnowledgeChunk.chunk_kind.is_(None))


def _build_retrieval_meta(
    *,
    retrieval_strategy: str,
    answer_source: str,
    scope_type: str,
    strict_mode: bool,
    top_k: int,
    compatible_file_count: int,
    candidate_chunks: int,
    matched_chunks: int,
    selected_chunks: int,
    used_file_ids: list[int],
    candidate_k: int,
    expanded_chunks: int,
    packed_chunks: int,
    context_chars: int,
    neighbor_window: int,
    dedupe_adjacent_chunks: bool,
    retrieval_mode: str,
    semantic_candidate_count: int,
    lexical_candidate_count: int,
    fusion_method: str,
    score_threshold_applied: float,
    rerank_enabled: bool,
    rerank_input_count: int,
    rerank_output_count: int,
    rerank_model_name: str,
    rerank_applied: bool,
    parent_recovered_chunks: int = 0,
    parent_deduped_groups: int = 0,
) -> dict:
    """Normalized retrieval_meta for API responses; keeps legacy min_score alongside min_similarity_score."""
    return {
        "retrieval_strategy": retrieval_strategy or DEFAULT_RETRIEVAL_STRATEGY,
        "answer_source": answer_source,
        "scope_type": scope_type,
        "strict_mode": strict_mode,
        "top_k": top_k,
        "min_similarity_score": MIN_SIMILARITY_SCORE,
        "candidate_chunks": candidate_chunks,
        "matched_chunks": matched_chunks,
        # Final chunks actually concatenated into the LLM context (same as packed_chunks when packing runs).
        "selected_chunks": selected_chunks,
        "compatible_file_count": compatible_file_count,
        "used_file_ids": used_file_ids,
        # Legacy field name (same value as min_similarity_score)
        "min_score": MIN_SIMILARITY_SCORE,
        "candidate_k": candidate_k,
        "expanded_chunks": expanded_chunks,
        "packed_chunks": packed_chunks,
        "context_chars": context_chars,
        "neighbor_window": neighbor_window,
        "dedupe_adjacent_chunks": dedupe_adjacent_chunks,
        "retrieval_mode": retrieval_mode,
        "semantic_candidate_count": semantic_candidate_count,
        "lexical_candidate_count": lexical_candidate_count,
        "fusion_method": fusion_method,
        "score_threshold_applied": score_threshold_applied,
        "rerank_enabled": rerank_enabled,
        "rerank_input_count": rerank_input_count,
        "rerank_output_count": rerank_output_count,
        "rerank_model_name": rerank_model_name,
        "rerank_applied": rerank_applied,
        "parent_recovered_chunks": parent_recovered_chunks,
        "parent_deduped_groups": parent_deduped_groups,
    }


def _truncate_ranked_to_candidate_k(ranked: list[dict], candidate_k: int) -> list[dict]:
    """Take the first candidate_k items from an already score-sorted ranked list."""
    if candidate_k < 1:
        return []
    return ranked[:candidate_k]


def _neighbor_score_from_seed(seed_score: float, index_distance: int) -> float:
    if index_distance <= 0:
        return seed_score
    return seed_score * (0.01 / (1 + abs(index_distance)))


def _score_neighbor_chunk(chunk: KnowledgeChunk, seeds: list[dict]) -> float:
    best = 0.0
    for item in seeds:
        sch = item["chunk"]
        if sch.file_id != chunk.file_id:
            continue
        dist = abs(chunk.chunk_index - sch.chunk_index)
        s = _neighbor_score_from_seed(item["score"], dist)
        if s > best:
            best = s
    return best


def _expand_neighbor_chunks(db: Session, seeds: list[dict], neighbor_window: int) -> list[dict]:
    """Load same-file chunks within ±neighbor_window of each seed chunk_index; seeds keep original scores."""
    if neighbor_window <= 0 or not seeds:
        return list(seeds)

    needed: dict[int, set[int]] = {}
    seed_ids = {item["chunk"].id for item in seeds}
    for item in seeds:
        ch = item["chunk"]
        lo = max(0, ch.chunk_index - neighbor_window)
        hi = ch.chunk_index + neighbor_window
        needed.setdefault(ch.file_id, set()).update(range(lo, hi + 1))

    by_id: dict[int, dict] = {}
    for item in seeds:
        by_id[item["chunk"].id] = {
            "chunk": item["chunk"],
            "file_name": item["file_name"],
            "folder_id": item.get("folder_id"),
            "score": item["score"],
        }

    for file_id, idxs in needed.items():
        rows = (
            db.query(KnowledgeChunk, FileRecord.file_name, FileRecord.folder_id)
            .join(FileRecord, KnowledgeChunk.file_id == FileRecord.id)
            .filter(KnowledgeChunk.file_id == file_id, KnowledgeChunk.chunk_index.in_(idxs))
            .filter(_child_or_legacy_retrieval_filter())
            .all()
        )
        for chunk, file_name, folder_id in rows:
            if chunk.id in by_id:
                continue
            by_id[chunk.id] = {
                "chunk": chunk,
                "file_name": file_name,
                "folder_id": folder_id,
                "score": _score_neighbor_chunk(chunk, seeds),
            }

    seed_order = [item["chunk"].id for item in seeds]
    rest = [cid for cid in by_id if cid not in seed_ids]
    rest_sorted = sorted(
        rest,
        key=lambda cid: (by_id[cid]["chunk"].file_id, by_id[cid]["chunk"].chunk_index),
    )
    ordered_ids = seed_order + rest_sorted
    return [by_id[cid] for cid in ordered_ids if cid in by_id]


def _dedupe_chunk_items(items: list[dict]) -> list[dict]:
    """Deduplicate by chunk.id; on conflict keep the highest score; preserve first-seen order."""
    best: dict[int, dict] = {}
    order: list[int] = []
    for item in items:
        cid = item["chunk"].id
        if cid not in best:
            best[cid] = item
            order.append(cid)
        elif item["score"] > best[cid]["score"]:
            best[cid] = item
    return [best[cid] for cid in order]


def _recover_parent_context_for_packing(
    db: Session,
    items: list[dict],
) -> tuple[list[dict], int]:
    """Merge siblings under same parent for packing; batch-load parents; set _pack_text / _used_parent_for_pack.

    Returns (items_for_packer, parent_deduped_groups). References still use child chunk from each kept item.
    """
    if not items:
        return [], 0
    winners: dict[tuple[str, int], dict] = {}
    for item in items:
        ch = item["chunk"]
        pid = getattr(ch, "parent_chunk_id", None)
        key: tuple[str, int] = ("p", int(pid)) if pid is not None else ("c", int(ch.id))
        if key not in winners or item["score"] > winners[key]["score"]:
            winners[key] = item
    seen: set[tuple[str, int]] = set()
    out: list[dict] = []
    for item in items:
        ch = item["chunk"]
        pid = getattr(ch, "parent_chunk_id", None)
        key = ("p", int(pid)) if pid is not None else ("c", int(ch.id))
        win = winners[key]
        if win is not item:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(win)
    parent_deduped_groups = len(out)
    parent_ids = {getattr(it["chunk"], "parent_chunk_id", None) for it in out}
    parent_ids.discard(None)
    parents: dict[int, KnowledgeChunk] = {}
    if parent_ids:
        for row in db.query(KnowledgeChunk).filter(KnowledgeChunk.id.in_(parent_ids)).all():
            parents[row.id] = row
    for it in out:
        ch = it["chunk"]
        pid = getattr(ch, "parent_chunk_id", None)
        use_parent = False
        body = ch.content or ""
        if pid is not None:
            par = parents.get(int(pid))
            if par is not None and (par.content or "").strip():
                body = par.content
                use_parent = True
        it["_pack_text"] = body
        it["_used_parent_for_pack"] = use_parent
    return out, parent_deduped_groups


def _pack_context_and_references(
    items: list[dict],
    *,
    seed_chunk_ids: set[int],
    max_context_chars: int,
    dedupe_adjacent_chunks: bool,
) -> tuple[list[str], list[dict], list[int], int, int, int]:
    """
    Greedy pack into max_context_chars. Prioritize seed hits (then by score, file, chunk_index).
    If item has _pack_text (parent recovery), use it for the LLM block body; references stay on child chunk.
    Returns context_blocks, references, used_files, context_chars, packed_chunks, parent_recovered_chunks.
    """
    if max_context_chars < 1:
        return [], [], [], 0, 0, 0

    def sort_key(it: dict) -> tuple:
        cid = it["chunk"].id
        is_seed = 1 if cid in seed_chunk_ids else 0
        return (-is_seed, -it["score"], it["chunk"].file_id, it["chunk"].chunk_index)

    sorted_items = sorted(items, key=sort_key)
    context_blocks: list[str] = []
    references: list[dict] = []
    used_files: list[int] = []
    total_chars = 0
    last_content_norm: str | None = None
    last_by_file: dict[int, tuple[int, str]] = {}
    parent_recovered_chunks = 0

    for item in sorted_items:
        chunk = item["chunk"]
        body = item.get("_pack_text")
        if body is None:
            body = chunk.content
        block = f"[文件: {item['file_name']} | chunk: {chunk.chunk_index}]\n{body}"
        sep = "\n\n" if context_blocks else ""
        add_len = len(sep) + len(block)
        if total_chars + add_len > max_context_chars:
            break
        content_norm = body.strip()
        if dedupe_adjacent_chunks and last_content_norm is not None and content_norm == last_content_norm:
            continue
        if dedupe_adjacent_chunks:
            prev = last_by_file.get(int(chunk.file_id))
            if prev is not None:
                prev_idx, prev_text = prev
                gap = abs(prev_idx - int(chunk.chunk_index))
                sim = _token_jaccard_similarity(prev_text, content_norm)
                if gap <= max(1, int(app_settings.qa_merge_adjacent_gap)) and sim >= float(app_settings.qa_redundancy_sim_threshold):
                    continue
        context_blocks.append(block)
        if item.get("_used_parent_for_pack"):
            parent_recovered_chunks += 1
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
        total_chars += add_len
        last_content_norm = content_norm
        last_by_file[int(chunk.file_id)] = (int(chunk.chunk_index), content_norm)

    return context_blocks, references, used_files, total_chars, len(references), parent_recovered_chunks


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
    references_json: list[dict] | dict | None,
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
        references_json=references_json,
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


def _token_jaccard_similarity(text_a: str, text_b: str) -> float:
    a = {tok for tok in re.findall(r"\w+", (text_a or "").lower()) if len(tok) > 1}
    b = {tok for tok in re.findall(r"\w+", (text_b or "").lower()) if len(tok) > 1}
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


def _apply_diversity_rerank(items: list[dict]) -> list[dict]:
    if not items or not app_settings.qa_diversity_rerank_enabled:
        return list(items)
    lam = max(0.0, min(1.0, float(app_settings.qa_diversity_lambda)))
    sim_th = max(0.0, min(1.0, float(app_settings.qa_redundancy_sim_threshold)))
    remaining = list(items)
    selected: list[dict] = []
    doc_counts: dict[int, int] = {}
    while remaining:
        best_idx = 0
        best_score = float("-inf")
        for idx, item in enumerate(remaining):
            ch = item["chunk"]
            doc_id = int(ch.file_id)
            rel = float(item.get("score", 0.0))
            doc_penalty = min(1.0, doc_counts.get(doc_id, 0) * 0.4)
            redundancy_penalty = 0.0
            for sel in selected[-8:]:
                sch = sel["chunk"]
                if sch.file_id != ch.file_id:
                    continue
                if abs(sch.chunk_index - ch.chunk_index) <= int(app_settings.qa_merge_adjacent_gap):
                    sim = _token_jaccard_similarity(sch.content or "", ch.content or "")
                    if sim >= sim_th:
                        redundancy_penalty = max(redundancy_penalty, sim)
            score = (1.0 - lam) * rel - lam * max(doc_penalty, redundancy_penalty)
            if score > best_score:
                best_score = score
                best_idx = idx
        chosen = remaining.pop(best_idx)
        selected.append(chosen)
        cdoc = int(chosen["chunk"].file_id)
        doc_counts[cdoc] = doc_counts.get(cdoc, 0) + 1
    return selected


def _enforce_doc_diversity(items: list[dict]) -> list[dict]:
    if not items:
        return []
    per_doc_cap = max(1, int(app_settings.qa_max_chunks_per_doc))
    target_docs = max(1, int(app_settings.qa_target_distinct_docs))
    min_docs = max(1, int(app_settings.qa_min_distinct_docs_for_multi_source))
    dominance = max(1.0, float(app_settings.qa_single_doc_dominance_ratio))

    by_doc: dict[int, list[dict]] = {}
    for it in items:
        by_doc.setdefault(int(it["chunk"].file_id), []).append(it)

    unique_docs = list(by_doc.keys())
    if len(unique_docs) < min_docs:
        out: list[dict] = []
        doc_cnt: dict[int, int] = {}
        for it in items:
            did = int(it["chunk"].file_id)
            if doc_cnt.get(did, 0) >= per_doc_cap:
                continue
            out.append(it)
            doc_cnt[did] = doc_cnt.get(did, 0) + 1
        logger.info(
            "Doc diversity skipped: unique_docs=%s min_docs=%s per_doc_cap=%s selected=%s",
            len(unique_docs),
            min_docs,
            per_doc_cap,
            doc_cnt,
        )
        return out

    doc_best = sorted(
        ((did, max(float(it.get("score", 0.0)) for it in rows)) for did, rows in by_doc.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    force_multi = True
    if len(doc_best) >= 2 and doc_best[1][1] > 0:
        force_multi = not (doc_best[0][1] >= doc_best[1][1] * dominance)
    selected_docs: set[int] = set()
    out: list[dict] = []
    doc_cnt: dict[int, int] = {}

    if force_multi:
        for did, _ in doc_best[:target_docs]:
            top_item = by_doc[did][0]
            out.append(top_item)
            selected_docs.add(did)
            doc_cnt[did] = 1

    for it in items:
        did = int(it["chunk"].file_id)
        if doc_cnt.get(did, 0) >= per_doc_cap:
            continue
        if force_multi and len(selected_docs) < target_docs and did not in selected_docs:
            selected_docs.add(did)
        out.append(it)
        doc_cnt[did] = doc_cnt.get(did, 0) + 1
    logger.info(
        "Doc diversity applied: force_multi=%s target_docs=%s selected_docs=%s per_doc_counts=%s",
        force_multi,
        target_docs,
        len({int(it['chunk'].file_id) for it in out}),
        doc_cnt,
    )
    return out


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
        .filter(_child_or_legacy_retrieval_filter())
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
        .filter(_child_or_legacy_retrieval_filter())
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


def _semantic_retrieval_app_layer(
    db: Session,
    *,
    query_embedding: list[float],
    compatible_file_ids: list[int],
    top_k: int,
) -> list[dict]:
    """Semantic (vector) retrieval; delegates to existing _retrieve_chunks."""
    return _retrieve_chunks(
        db,
        query_embedding=query_embedding,
        compatible_file_ids=compatible_file_ids,
        top_k=top_k,
    )


def _semantic_retrieval_pgvector(
    db: Session,
    *,
    query_embedding: list[float],
    compatible_file_ids: list[int],
    top_k: int,
) -> list[dict]:
    if not compatible_file_ids or not query_embedding:
        return []
    try:
        distance_expr = KnowledgeChunk.embedding_vec.cosine_distance(query_embedding)
        rows = (
            db.query(KnowledgeChunk, FileRecord.file_name, FileRecord.folder_id, distance_expr.label("distance"))
            .join(FileRecord, KnowledgeChunk.file_id == FileRecord.id)
            .filter(KnowledgeChunk.file_id.in_(compatible_file_ids))
            .filter(_child_or_legacy_retrieval_filter())
            .filter(KnowledgeChunk.embedding_vec.is_not(None))
            .order_by(distance_expr.asc())
            .limit(top_k)
            .all()
        )
    except Exception:
        logger.exception("pgvector semantic retrieval failed; fallback to app-layer cosine")
        raise

    ranked: list[dict] = []
    for chunk, file_name, folder_id, distance in rows:
        dist = float(distance) if distance is not None else 1.0
        score = max(0.0, 1.0 - dist)
        ranked.append(
            {
                "chunk": chunk,
                "file_name": file_name,
                "folder_id": folder_id,
                "score": score,
                "source": "semantic",
            }
        )
    ranked.sort(key=lambda it: it["score"], reverse=True)
    return ranked[:top_k]


def _semantic_retrieval(
    db: Session,
    *,
    query_embeddings: list[list[float]],
    compatible_file_ids: list[int],
    top_k: int,
) -> tuple[list[dict], str]:
    if not query_embeddings:
        return [], DEFAULT_RETRIEVAL_STRATEGY

    # Primary path: pgvector ANN
    if app_settings.qa_pgvector_retrieval_enabled and app_settings.qa_pgvector_semantic_enabled:
        all_candidates: dict[int, dict] = {}
        try:
            probe_limit = max(top_k, int(app_settings.qa_pgvector_probe_limit))
            for query_embedding in query_embeddings:
                for item in _semantic_retrieval_pgvector(
                    db,
                    query_embedding=query_embedding,
                    compatible_file_ids=compatible_file_ids,
                    top_k=probe_limit,
                ):
                    cid = item["chunk"].id
                    if cid not in all_candidates or item["score"] > all_candidates[cid]["score"]:
                        all_candidates[cid] = item
            merged = list(all_candidates.values())
            merged.sort(key=lambda it: it["score"], reverse=True)
            if merged:
                return merged[:top_k], "pgvector_ann_hnsw"
        except Exception:
            logger.info("pgvector unavailable; switching to app-layer cosine fallback")

    # Fallback: app-layer cosine scan
    all_candidates: dict[int, dict] = {}
    for query_embedding in query_embeddings:
        for item in _semantic_retrieval_app_layer(
            db,
            query_embedding=query_embedding,
            compatible_file_ids=compatible_file_ids,
            top_k=max(top_k, int(app_settings.qa_pgvector_probe_limit)),
        ):
            cid = item["chunk"].id
            item["source"] = "semantic"
            if cid not in all_candidates or item["score"] > all_candidates[cid]["score"]:
                all_candidates[cid] = item
    merged = list(all_candidates.values())
    merged.sort(key=lambda it: it["score"], reverse=True)
    return merged[:top_k], DEFAULT_RETRIEVAL_STRATEGY


def _lexical_retrieval(
    db: Session,
    *,
    questions: list[str],
    compatible_file_ids: list[int],
    top_k: int,
) -> list[dict]:
    """Lexical retrieval via PostgreSQL FTS.

    Priority:
    1. KnowledgeChunk.search_vector @@ websearch_to_tsquery (uses GIN index)
    2. Fallback: inline to_tsvector(content) @@ websearch_to_tsquery
    """
    if not compatible_file_ids or not questions:
        return []

    def _do_query(tsvector_expr, q: str) -> list[dict]:
        query = (
            db.query(KnowledgeChunk, FileRecord.file_name, FileRecord.folder_id)
            .join(FileRecord, KnowledgeChunk.file_id == FileRecord.id)
            .filter(KnowledgeChunk.file_id.in_(compatible_file_ids))
            .filter(_child_or_legacy_retrieval_filter())
            .filter(
                tsvector_expr.op("@@")(
                    func.websearch_to_tsquery("simple", q)
                )
            )
            .order_by(KnowledgeChunk.id.asc())
            .limit(top_k)
        )

        ranked: list[dict] = []
        for chunk, file_name, folder_id in query.all():
            ranked.append(
                {
                    "chunk": chunk,
                    "file_name": file_name,
                    "folder_id": folder_id,
                    # Lightweight lexical score; NOT comparable to semantic cosine.
                    # RRF fusion normalizes by rank, so absolute value doesn't matter.
                    "score": 1.0,
                    "source": "lexical",
                }
            )
        return ranked

    merged: dict[int, dict] = {}
    for q in questions:
        if not q.strip():
            continue
        # 1) Prefer search_vector (indexed GIN column)
        try:
            result = _do_query(KnowledgeChunk.search_vector, q)
        except Exception:
            result = []
        # 2) Fallback: inline to_tsvector(content)
        if not result:
            try:
                result = _do_query(
                    func.to_tsvector(
                        "simple",
                        func.coalesce(KnowledgeChunk.content, ""),
                    ),
                    q,
                )
            except Exception:
                result = []
        for item in result:
            cid = item["chunk"].id
            if cid not in merged:
                merged[cid] = item
    out = list(merged.values())
    out.sort(key=lambda it: (it["chunk"].file_id, it["chunk"].chunk_index))
    return out[:top_k]


_RRF_K = 60


def _dedup_key(item: dict) -> int:
    """Primary dedup by chunk.id; fallback to (file_id, chunk_index) composite."""
    chunk = item["chunk"]
    return chunk.id


def _fuse_retrieval_results(
    semantic_matches: list[dict],
    lexical_matches: list[dict],
) -> list[dict]:
    """Fuse semantic and lexical ranked lists via RRF (Reciprocal Rank Fusion).

    rrf_score = sum(1 / (k + rank))  for each list where the chunk appears.
    k = _RRF_K (60).  Rank is 1-based.
    """
    if not semantic_matches and not lexical_matches:
        return []
    if not semantic_matches:
        fused = _apply_rrf_to_single_list(lexical_matches)
        return fused
    if not lexical_matches:
        fused = _apply_rrf_to_single_list(semantic_matches)
        return fused

    # Both non-empty → full RRF fusion.
    scores: dict[int, float] = {}
    sources: dict[int, set[str]] = {}
    items: dict[int, dict] = {}

    for rank, item in enumerate(semantic_matches, start=1):
        key = _dedup_key(item)
        scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank)
        sources.setdefault(key, set()).add("semantic")
        if key not in items:
            items[key] = {
                "chunk": item["chunk"],
                "file_name": item["file_name"],
                "folder_id": item["folder_id"],
                "score": 0.0,
                "source": "",
            }

    for rank, item in enumerate(lexical_matches, start=1):
        key = _dedup_key(item)
        scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank)
        sources.setdefault(key, set()).add("lexical")
        if key not in items:
            items[key] = {
                "chunk": item["chunk"],
                "file_name": item["file_name"],
                "folder_id": item["folder_id"],
                "score": 0.0,
                "source": "",
            }

    for key in items:
        src = sources.get(key, set())
        if src == {"semantic", "lexical"}:
            source_tag = "hybrid"
        elif "semantic" in src:
            source_tag = "semantic"
        else:
            source_tag = "lexical"
        items[key]["score"] = scores[key]
        items[key]["source"] = source_tag

    fused = list(items.values())
    fused.sort(key=lambda it: it["score"], reverse=True)
    return fused


def _apply_rrf_to_single_list(matches: list[dict]) -> list[dict]:
    """When only one list exists, assign RRF scores so downstream logic stays uniform."""
    source_tag = "semantic" if matches and _is_semantic(matches[0]) else "lexical"
    result = []
    for rank, item in enumerate(matches, start=1):
        result.append({
            "chunk": item["chunk"],
            "file_name": item["file_name"],
            "folder_id": item["folder_id"],
            "score": 1.0 / (_RRF_K + rank),
            "source": source_tag,
        })
    return result


def _is_semantic(item: dict) -> bool:
    """Heuristic to tag source when only one list is present."""
    return "source" in item and item["source"] == "semantic"


def _rerank_matches(
    matches: list[dict],
    *,
    question: str,
    rerank_enabled: bool,
    rerank_top_n: int,
    rerank_model_name: str,
) -> tuple[list[dict], bool]:
    """Rerank fused matches using a local cross-encoder.

    Returns (reranked_matches, rerank_applied).
    - If rerank_enabled is False, returns (matches, False).
    - If model load or scoring fails, falls back to (matches, False).
    """
    if not rerank_enabled or not matches or not question.strip():
        return list(matches), False

    try:
        from sentence_transformers import CrossEncoder  # noqa: PLC0415
    except ImportError:
        logger.info("sentence-transformers not installed; skipping rerank")
        return list(matches), False

    # Module-level model cache
    if not hasattr(_rerank_matches, "_model_cache"):
        _rerank_matches._model_cache = {}  # type: ignore[attr-defined]
        _rerank_matches._model_lock = False  # type: ignore[attr-defined]

    cache = _rerank_matches._model_cache
    model = cache.get(rerank_model_name)
    if model is None:
        try:
            model = CrossEncoder(rerank_model_name, max_length=512)
            cache[rerank_model_name] = model
        except Exception:
            logger.exception("Failed to load rerank model '%s'", rerank_model_name)
            return list(matches), False

    # Only rerank the top rerank_top_n candidates
    top_n = max(1, rerank_top_n)
    rerank_candidates = matches[:top_n]
    rest = matches[top_n:]
    started = time.perf_counter()
    budget_ms = max(100, int(app_settings.qa_rerank_latency_budget_ms))

    try:
        sentence_pairs = [
            (question, item["chunk"].content or "")
            for item in rerank_candidates
        ]
        scores = model.predict(sentence_pairs, show_progress_bar=False)
    except Exception:
        logger.exception("Rerank scoring failed for model '%s'", rerank_model_name)
        return list(matches), False
    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms > budget_ms:
        logger.warning(
            "Rerank latency budget exceeded: model=%s elapsed_ms=%.2f budget_ms=%s",
            rerank_model_name,
            elapsed_ms,
            budget_ms,
        )

    for item, s in zip(rerank_candidates, scores):
        item["rerank_score"] = float(s)

    rerank_candidates.sort(key=lambda it: it.get("rerank_score", 0.0), reverse=True)

    return rerank_candidates + rest, True


MODEL_NON_KB_PREFIX = "以下内容不基于知识库\n\n"


def _build_context_from_matches(items: list[dict]) -> tuple[list[str], list[dict], list[int]]:
    context_blocks: list[str] = []
    references: list[dict] = []
    used_files: list[int] = []
    for item in items:
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
    return context_blocks, references, used_files


def _qa_chat_completion(settings: SystemSetting, *, system: str, user: str) -> str:
    return chat_completion(
        provider=settings.llm_provider,
        api_base=settings.llm_api_base,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )


def ask_question(
    db: Session,
    *,
    question: str,
    scope_type: str,
    folder_id: int | None,
    file_ids: list[int] | None,
    strict_mode: bool,
    top_k: int,
    candidate_k: int | None = None,
    max_context_chars: int | None = None,
    neighbor_window: int | None = None,
    dedupe_adjacent_chunks: bool | None = None,
    rerank_enabled: bool | None = None,
    rerank_top_n: int | None = None,
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
    candidate_k = max(1, candidate_k if candidate_k is not None else app_settings.qa_candidate_k)
    neighbor_window = max(0, neighbor_window if neighbor_window is not None else app_settings.qa_neighbor_window)
    max_context_chars = max(1, max_context_chars if max_context_chars is not None else app_settings.qa_max_context_chars)
    dedupe_adjacent = bool(
        dedupe_adjacent_chunks
        if dedupe_adjacent_chunks is not None
        else app_settings.qa_dedupe_adjacent_chunks
    )
    eff_rerank_enabled = (
        bool(rerank_enabled)
        if rerank_enabled is not None
        else bool(app_settings.qa_rerank_enabled)
    )
    eff_rerank_top_n = (
        max(1, rerank_top_n)
        if rerank_top_n is not None
        else max(1, app_settings.qa_rerank_top_n)
    )
    pool_limit = min(QA_RETRIEVAL_POOL_CAP, max(MIN_TOP_K, top_k, candidate_k))

    retrieval_mode = _normalize_retrieval_mode(app_settings.qa_retrieval_mode)
    query_variants = _build_query_variants(question)
    try:
        query_embeddings = embed_texts(
            provider=settings.embedding_provider,
            api_base=settings.embedding_api_base,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            inputs=query_variants,
            embedding_batch_size_from_db=settings.embedding_batch_size,
        )
    except RuntimeError as exc:
        raise QAServiceError("MODEL_REQUEST_FAILED", "模型服务请求失败，请检查当前配置与连接状态") from exc
    if not query_embeddings:
        raise QAServiceError("EMBEDDING_DATA_UNAVAILABLE", "查询向量为空，无法执行检索")

    compatible_file_ids = _collect_retrievable_file_ids(
        db,
        settings=settings,
        scope_type=scope_type,
        folder_id=folder_id,
        file_ids=file_ids,
        expected_dimension=len(query_embeddings[0]),
    )
    if not compatible_file_ids:
        if strict_mode:
            raise QAServiceError(
                "NO_COMPATIBLE_INDEXED_CONTENT",
                "当前范围内没有可用于当前知识库索引标准的已索引文献，请先建立或重建索引。",
            )
        user_prompt = (
            "当前问答范围内没有可用于当前知识库索引标准的已索引文献，无法从知识库取得任何可引用片段。\n"
            "请基于你的通用知识直接回答用户问题。\n"
            "要求：不要虚构本知识库中的文献或条文；不要使用「根据上传文件」「资料中记载」等表述。\n\n"
            f"问题：{question}"
        )
        system_msg = (
            "用户处于非严格问答模式，且当前范围内没有可检索的知识库内容；请用通用知识作答，切勿伪造知识库引用。"
        )
        try:
            answer = _qa_chat_completion(settings, system=system_msg, user=user_prompt)
        except RuntimeError as exc:
            raise QAServiceError("MODEL_REQUEST_FAILED", "模型服务请求失败，请检查当前配置与连接状态") from exc
        answer = MODEL_NON_KB_PREFIX + answer
        refs_payload = {"answer_source": "model_general", "references": []}
        retrieval_meta = _build_retrieval_meta(
            retrieval_strategy=DEFAULT_RETRIEVAL_STRATEGY,
            answer_source="model_general",
            scope_type=scope_type,
            strict_mode=strict_mode,
            top_k=top_k,
            compatible_file_count=0,
            candidate_chunks=0,
            matched_chunks=0,
            selected_chunks=0,
            used_file_ids=[],
            candidate_k=candidate_k,
            expanded_chunks=0,
            packed_chunks=0,
            context_chars=0,
            neighbor_window=neighbor_window,
            dedupe_adjacent_chunks=dedupe_adjacent,
            retrieval_mode=retrieval_mode,
            semantic_candidate_count=0,
            lexical_candidate_count=0,
            fusion_method="none",
            score_threshold_applied=MIN_SIMILARITY_SCORE,
            rerank_enabled=eff_rerank_enabled,
            rerank_input_count=0,
            rerank_output_count=0,
            rerank_model_name=app_settings.qa_rerank_model_name,
            rerank_applied=False,
            parent_recovered_chunks=0,
            parent_deduped_groups=0,
        )
        return {
            "answer": answer,
            "references": [],
            "references_json": refs_payload,
            "answer_source": "model_general",
            "used_files": [],
            "retrieval_meta": retrieval_meta,
        }

    retrieval_strategy = DEFAULT_RETRIEVAL_STRATEGY
    semantic_matches: list[dict] = []
    lexical_matches: list[dict] = []
    if retrieval_mode in {"semantic", "hybrid"}:
        semantic_matches, semantic_strategy = _semantic_retrieval(
            db,
            query_embeddings=query_embeddings,
            compatible_file_ids=compatible_file_ids,
            top_k=pool_limit,
        )
        retrieval_strategy = semantic_strategy
    if retrieval_mode in {"lexical", "hybrid"}:
        lexical_matches = _lexical_retrieval(
            db,
            questions=query_variants,
            compatible_file_ids=compatible_file_ids,
            top_k=pool_limit,
        )
    if retrieval_mode == "semantic":
        matches = semantic_matches
    elif retrieval_mode == "lexical":
        matches = _apply_rrf_to_single_list(lexical_matches)
        retrieval_strategy = "fts_websearch_rrf"
    else:
        matches = _fuse_retrieval_results(semantic_matches, lexical_matches)

    # --- Rerank ---
    rerank_input_count = len(matches)
    matches, rerank_applied = _rerank_matches(
        matches,
        question=question,
        rerank_enabled=eff_rerank_enabled,
        rerank_top_n=eff_rerank_top_n,
        rerank_model_name=app_settings.qa_rerank_model_name,
    )
    matches = _apply_diversity_rerank(matches)
    rerank_output_count = len(matches)

    candidate_matches = _truncate_ranked_to_candidate_k(matches, candidate_k)
    score_threshold_applied = _score_threshold_for_mode(retrieval_mode)
    reliable_matches = [item for item in candidate_matches if item["score"] >= score_threshold_applied]
    compatible_count = len(compatible_file_ids)
    initial_docs = len({int(it["chunk"].file_id) for it in matches})
    reliable_docs = len({int(it["chunk"].file_id) for it in reliable_matches})
    logger.info(
        "QA retrieval mode=%s strategy=%s compatible_files=%s semantic=%s lexical=%s fused=%s unique_docs=%s reliable=%s reliable_docs=%s threshold=%.4f rerank=%s diversity=%s",
        retrieval_mode,
        retrieval_strategy,
        compatible_count,
        len(semantic_matches),
        len(lexical_matches),
        len(matches),
        initial_docs,
        len(reliable_matches),
        reliable_docs,
        score_threshold_applied,
        rerank_applied,
        app_settings.qa_diversity_rerank_enabled,
    )

    try:
        if strict_mode:
            if not candidate_matches:
                raise QAServiceError(
                    "NO_RELIABLE_EVIDENCE",
                    "知识库中未检索到可用资料，严格模式下无法回答。",
                )
            if not reliable_matches:
                raise QAServiceError(
                    "NO_RELIABLE_EVIDENCE",
                    "知识库中未找到足够相关的依据，严格模式下无法回答。",
                )
            expanded_items = _expand_neighbor_chunks(db, reliable_matches, neighbor_window)
            expanded_n = len(expanded_items)
            deduped_items = _dedupe_chunk_items(expanded_items)
            diversified_items = _enforce_doc_diversity(deduped_items)
            pack_items, parent_deduped_groups = _recover_parent_context_for_packing(db, diversified_items)
            seed_ids = {item["chunk"].id for item in reliable_matches}
            (
                context_blocks,
                references,
                used_files,
                context_chars,
                packed_n,
                parent_recovered_chunks,
            ) = _pack_context_and_references(
                pack_items,
                seed_chunk_ids=seed_ids,
                max_context_chars=max_context_chars,
                dedupe_adjacent_chunks=dedupe_adjacent,
            )
            if packed_n < max(1, int(app_settings.qa_strict_min_citations)):
                raise QAServiceError(
                    "NO_RELIABLE_EVIDENCE",
                    "知识库证据不足，严格模式下无法给出可引用回答。",
                )
            user_prompt = (
                "你是实验室内部知识库问答助手。你只允许根据下方「资料片段」回答问题。\n"
                "要求：\n"
                "- 结论必须可由资料支撑；不要引入资料未提及的关键事实。\n"
                "- 若资料来自多个文件且互补，请优先综合增量信息，避免重复转述同一来源的相邻片段。\n"
                "- 若资料不足以回答用户问题，请明确说明无法根据当前知识库资料作出完整回答，不要猜测，"
                "也不要改用通用知识或常识来替代知识库依据。\n\n"
                f"问题：{question}\n\n资料片段：\n"
                + "\n\n".join(context_blocks)
            )
            system_msg = (
                "你是一个只依据用户给定的知识库片段作答的助手；无充分依据时不臆测，也不使用课外知识兜底。"
            )
            answer = _qa_chat_completion(settings, system=system_msg, user=user_prompt)
            retrieval_meta = _build_retrieval_meta(
                retrieval_strategy=retrieval_strategy,
                answer_source="knowledge_base",
                scope_type=scope_type,
                strict_mode=strict_mode,
                top_k=top_k,
                compatible_file_count=compatible_count,
                candidate_chunks=len(matches),
                matched_chunks=len(reliable_matches),
                selected_chunks=packed_n,
                used_file_ids=list(used_files),
                candidate_k=candidate_k,
                expanded_chunks=expanded_n,
                packed_chunks=packed_n,
                context_chars=context_chars,
                neighbor_window=neighbor_window,
                dedupe_adjacent_chunks=dedupe_adjacent,
                retrieval_mode=retrieval_mode,
                semantic_candidate_count=len(semantic_matches),
                lexical_candidate_count=len(lexical_matches),
                fusion_method=("rrf" if retrieval_mode == "hybrid" else retrieval_mode),
                score_threshold_applied=score_threshold_applied,
                rerank_enabled=eff_rerank_enabled,
                rerank_input_count=rerank_input_count,
                rerank_output_count=rerank_output_count,
                rerank_model_name=app_settings.qa_rerank_model_name,
                rerank_applied=rerank_applied,
                parent_recovered_chunks=parent_recovered_chunks,
                parent_deduped_groups=parent_deduped_groups,
            )
            return {
                "answer": answer,
                "references": references,
                "references_json": references,
                "answer_source": "knowledge_base",
                "used_files": used_files,
                "retrieval_meta": retrieval_meta,
            }

        if reliable_matches:
            expanded_items = _expand_neighbor_chunks(db, reliable_matches, neighbor_window)
            expanded_n = len(expanded_items)
            deduped_items = _dedupe_chunk_items(expanded_items)
            diversified_items = _enforce_doc_diversity(deduped_items)
            pack_items, parent_deduped_groups = _recover_parent_context_for_packing(db, diversified_items)
            seed_ids = {item["chunk"].id for item in reliable_matches}
            (
                context_blocks,
                references,
                used_files,
                context_chars,
                packed_n,
                parent_recovered_chunks,
            ) = _pack_context_and_references(
                pack_items,
                seed_chunk_ids=seed_ids,
                max_context_chars=max_context_chars,
                dedupe_adjacent_chunks=dedupe_adjacent,
            )
            user_prompt = (
                "你是实验室知识库问答助手。请优先根据下方「资料片段」回答问题。\n"
                "要求：\n"
                "- 当资料足以支撑结论时，以资料为准，回答应体现资料中的要点。\n"
                "- 若多个来源提供互补证据，请合并关键增量信息，不要机械重复同一来源相邻片段。\n"
                "- 若资料仅有部分相关信息，可先说明资料中的依据，再在必要时少量结合常识补充，"
                "但不要与资料矛盾，也不要虚构资料中不存在的内容或引用。\n"
                "- 若资料明显不足以判断用户问题，请说明资料局限，不要假装资料已覆盖。\n\n"
                f"问题：{question}\n\n资料片段：\n"
                + "\n\n".join(context_blocks)
            )
            system_msg = (
                "你优先依据用户提供的知识库资料作答；仅在资料边界清晰的前提下可谨慎补充常识，不伪造知识库内容。"
            )
            answer = _qa_chat_completion(settings, system=system_msg, user=user_prompt)
            retrieval_meta = _build_retrieval_meta(
                retrieval_strategy=retrieval_strategy,
                answer_source="knowledge_base",
                scope_type=scope_type,
                strict_mode=strict_mode,
                top_k=top_k,
                compatible_file_count=compatible_count,
                candidate_chunks=len(matches),
                matched_chunks=len(reliable_matches),
                selected_chunks=packed_n,
                used_file_ids=list(used_files),
                candidate_k=candidate_k,
                expanded_chunks=expanded_n,
                packed_chunks=packed_n,
                context_chars=context_chars,
                neighbor_window=neighbor_window,
                dedupe_adjacent_chunks=dedupe_adjacent,
                retrieval_mode=retrieval_mode,
                semantic_candidate_count=len(semantic_matches),
                lexical_candidate_count=len(lexical_matches),
                fusion_method=("rrf" if retrieval_mode == "hybrid" else retrieval_mode),
                score_threshold_applied=score_threshold_applied,
                rerank_enabled=eff_rerank_enabled,
                rerank_input_count=rerank_input_count,
                rerank_output_count=rerank_output_count,
                rerank_model_name=app_settings.qa_rerank_model_name,
                rerank_applied=rerank_applied,
                parent_recovered_chunks=parent_recovered_chunks,
                parent_deduped_groups=parent_deduped_groups,
            )
            return {
                "answer": answer,
                "references": references,
                "references_json": references,
                "answer_source": "knowledge_base",
                "used_files": used_files,
                "retrieval_meta": retrieval_meta,
            }

        low_rel_note = ""
        if candidate_matches:
            low_rel_note = (
                "说明：知识库中检索到少量片段，但相似度未达到采用为「知识库依据」的阈值，"
                "故不将检索片段作为引用依据。请完全基于你的通用知识回答，不要引用或编造具体知识库文件名或片段。\n\n"
            )
        user_prompt = (
            "当前没有可作为依据的知识库资料片段供你引用。\n"
            + low_rel_note
            + "请基于你的通用知识直接回答用户问题。\n"
            "要求：不要虚构本知识库中的文献或条文；不要使用「根据上传文件」「资料中记载」等表述。\n\n"
            f"问题：{question}"
        )
        system_msg = (
            "用户处于非严格问答模式，且当前没有可用的知识库片段；请用通用知识作答，切勿伪造知识库引用。"
        )
        answer = _qa_chat_completion(settings, system=system_msg, user=user_prompt)
        answer = MODEL_NON_KB_PREFIX + answer
        low_confidence = bool(candidate_matches)
        answer_src = "knowledge_base_low_confidence" if low_confidence else "model_general"
        refs_payload = {"answer_source": answer_src, "references": []}
        retrieval_meta = _build_retrieval_meta(
            retrieval_strategy=retrieval_strategy,
            answer_source=answer_src,
            scope_type=scope_type,
            strict_mode=strict_mode,
            top_k=top_k,
            compatible_file_count=compatible_count,
            candidate_chunks=len(matches),
            matched_chunks=len(reliable_matches),
            selected_chunks=0,
            used_file_ids=[],
            candidate_k=candidate_k,
            expanded_chunks=0,
            packed_chunks=0,
            context_chars=0,
            neighbor_window=neighbor_window,
            dedupe_adjacent_chunks=dedupe_adjacent,
            retrieval_mode=retrieval_mode,
            semantic_candidate_count=len(semantic_matches),
            lexical_candidate_count=len(lexical_matches),
            fusion_method=("rrf" if retrieval_mode == "hybrid" else retrieval_mode),
            score_threshold_applied=score_threshold_applied,
            rerank_enabled=eff_rerank_enabled,
            rerank_input_count=rerank_input_count,
            rerank_output_count=rerank_output_count,
            rerank_model_name=app_settings.qa_rerank_model_name,
            rerank_applied=rerank_applied,
            parent_recovered_chunks=0,
            parent_deduped_groups=0,
        )
        return {
            "answer": answer,
            "references": [],
            "references_json": refs_payload,
            "answer_source": answer_src,
            "used_files": [],
            "retrieval_meta": retrieval_meta,
        }
    except RuntimeError as exc:
        raise QAServiceError("MODEL_REQUEST_FAILED", "模型服务请求失败，请检查当前配置与连接状态") from exc


def persist_qa_citations(
    db: Session,
    *,
    message_id: int,
    references: list[dict] | None,
) -> None:
    """Insert normalized citation rows for a successful assistant message."""
    if not references:
        return
    for order, ref in enumerate(references):
        if not isinstance(ref, dict):
            continue
        try:
            file_id = int(ref["file_id"])
            chunk_id = int(ref["chunk_id"])
        except (KeyError, TypeError, ValueError):
            continue
        chunk_index = int(ref.get("chunk_index", 0))
        page = ref.get("page_number")
        page_number = int(page) if page is not None else None
        st = ref.get("section_title")
        section_title = (str(st)[:500] if st is not None else None)
        score_v = ref.get("score")
        try:
            score_f = float(score_v) if score_v is not None else None
        except (TypeError, ValueError):
            score_f = None
        db.add(
            QACitation(
                message_id=message_id,
                file_id=file_id,
                chunk_id=chunk_id,
                chunk_index=chunk_index,
                page_number=page_number,
                section_title=section_title,
                score=score_f,
                citation_order=order,
            )
        )
    db.commit()


def persist_retrieval_trace(
    db: Session,
    *,
    session_id: int,
    assistant_message_id: int | None,
    question: str,
    retrieval_meta: dict | None,
    answer_source: str | None,
    debug_json: dict | None = None,
) -> None:
    """Persist one retrieval trace row (success or failure)."""
    meta = retrieval_meta or {}
    dbg = debug_json if debug_json is not None else (dict(meta) if meta else None)
    trace = QARetrievalTrace(
        session_id=session_id,
        assistant_message_id=assistant_message_id,
        question=question,
        retrieval_mode=meta.get("retrieval_mode"),
        fusion_method=meta.get("fusion_method"),
        top_k=meta.get("top_k"),
        candidate_k=meta.get("candidate_k"),
        candidate_chunks=meta.get("candidate_chunks"),
        matched_chunks=meta.get("matched_chunks"),
        selected_chunks=meta.get("selected_chunks"),
        score_threshold_applied=meta.get("score_threshold_applied"),
        answer_source=answer_source or meta.get("answer_source"),
        rerank_enabled=meta.get("rerank_enabled"),
        rerank_applied=meta.get("rerank_applied"),
        rerank_model_name=meta.get("rerank_model_name"),
        debug_json=dbg,
    )
    db.add(trace)
    db.commit()
