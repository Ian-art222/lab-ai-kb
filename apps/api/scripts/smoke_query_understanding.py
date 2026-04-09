#!/usr/bin/env python3
"""最小 smoke：验证 query 理解模块可导入并产出结构化结果（无需 DB）。

运行: cd apps/api && python scripts/smoke_query_understanding.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.qa_agent_workflow import route_task_scope_skill
from app.services.query_understanding import build_query_analysis, compact_query_trace_for_meta


def main() -> None:
    q = "请问如何比较方案 A 与方案 B 的部署步骤差异，如果启动失败该怎么办？"
    routing = route_task_scope_skill(question=q, scope_type="all", file_ids=None)
    nq = " ".join(q.split())
    analysis = build_query_analysis(
        q,
        routing=routing,
        normalized_query=nq,
        base_variants=[nq],
    )
    compact = compact_query_trace_for_meta(analysis)
    assert analysis.get("query_type")
    assert analysis.get("retrieval_queries")
    print("query_type:", analysis.get("query_type"))
    print("retrieval_queries:", analysis.get("retrieval_queries"))
    print("compact_meta_keys:", sorted(compact.keys()))
    print("smoke_ok")


if __name__ == "__main__":
    main()
