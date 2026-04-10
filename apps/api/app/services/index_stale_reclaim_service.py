"""索引僵尸任务自动回收：依赖 index_status_updated_at / index_run_started_at。"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.file_record import FileRecord
from app.services.ingest_service import _mark_index_failure
from app.services.pdf_document_service import get_by_file_id, sync_index_status
from app.services.pdf_ingest_bridge_service import is_file_ingest_active

logger = logging.getLogger(__name__)

_PROCESSING_STATUSES = frozenset({"indexing", "parsing", "chunking", "embedding", "reindexing"})
_reclaim_lock = threading.Lock()


def reclaim_stale_index_jobs(db: Session) -> int:
    """将超时未完成的索引行标记为 failed；跳过当前进程内正在执行 ingest 的 file_id。"""
    if not settings.index_stale_reclaim_enabled:
        return 0

    now = datetime.utcnow()
    pending_cutoff = now - timedelta(minutes=max(1, settings.index_stale_pending_minutes))
    proc_cutoff = now - timedelta(minutes=max(1, settings.index_stale_processing_minutes))

    candidate_ids = [
        row[0]
        for row in db.query(FileRecord.id)
        .filter(FileRecord.index_status.notin_(["indexed", "failed", "partial_failed"]))
        .order_by(FileRecord.id.asc())
        .all()
    ]

    reclaimed = 0
    for fid in candidate_ids:
        if is_file_ingest_active(fid):
            continue

        fr = db.query(FileRecord).filter(FileRecord.id == fid).first()
        if fr is None:
            continue

        st = (fr.index_status or "").strip()
        updated = fr.index_status_updated_at
        run_started = fr.index_run_started_at

        stale_queue = (
            st == "pending"
            and run_started is None
            and (updated is None or updated < pending_cutoff)
        )
        stale_process = st in _PROCESSING_STATUSES and (updated is None or updated < proc_cutoff)
        stale_pending_weird = (
            st == "pending"
            and run_started is not None
            and (updated is None or updated < proc_cutoff)
        )

        if not (stale_queue or stale_process or stale_pending_weird):
            continue

        if stale_queue:
            reason = (
                f"索引任务超时未开始执行（排队超过 {settings.index_stale_pending_minutes} 分钟）。"
                "可能后台任务未调度或服务已重启，请重新建立索引。"
            )
            code = "stale_reclaim_pending"
        else:
            reason = (
                f"索引处理中断或超时（原状态「{st}」，超过 {settings.index_stale_processing_minutes} 分钟无进展）。"
                "已自动回收，请重新建立索引。"
            )
            code = "stale_reclaim_processing"

        logger.warning(
            "index stale reclaim: file_id=%s file_name=%r old_status=%s index_status_updated_at=%s "
            "index_run_started_at=%s -> failed code=%s",
            fid,
            (fr.file_name or "")[:160],
            st,
            updated.isoformat() if updated else None,
            run_started.isoformat() if run_started else None,
            code,
        )

        _mark_index_failure(db, file_id=fid, error_message=reason, error_code=code)
        pdf_doc = get_by_file_id(db, fid)
        if pdf_doc:
            file_row = db.query(FileRecord).filter(FileRecord.id == fid).first()
            if file_row:
                sync_index_status(db, doc=pdf_doc, file_record=file_row)
        reclaimed += 1

    return reclaimed


def run_stale_reclaim_once() -> int:
    """单实例互斥，供启动与周期线程调用。"""
    with _reclaim_lock:
        db = SessionLocal()
        try:
            n = reclaim_stale_index_jobs(db)
            if n:
                logger.info("index stale reclaim scan done reclaimed=%s", n)
            return n
        finally:
            db.close()
