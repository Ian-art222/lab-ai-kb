from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings


def record_failure_case(payload: dict[str, Any]) -> None:
    path = Path(settings.qa_failure_cases_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "created_at": datetime.utcnow().isoformat(),
        **payload,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

