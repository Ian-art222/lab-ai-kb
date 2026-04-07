from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


def _failure_cases_path() -> Path:
    base = Path(settings.qa_failure_cases_dir)
    base.mkdir(parents=True, exist_ok=True)
    return base / "qa_failure_cases.jsonl"


def sink_failure_case(payload: dict[str, Any]) -> None:
    """Best-effort failure case sink; must never break request path."""
    try:
        path = _failure_cases_path()
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("Failed to persist failure case")


def build_failure_case(
    *,
    query: str,
    trace_id: str,
    request_id: str | None,
    reason_code: str,
    answer_summary: str,
    retrieved_refs: list[dict] | None,
) -> dict[str, Any]:
    return {
        "query": query,
        "trace_id": trace_id,
        "request_id": request_id,
        "reason_code": reason_code,
        "answer_summary": answer_summary,
        "retrieved_refs": retrieved_refs or [],
        "created_at": datetime.utcnow().isoformat(),
    }
