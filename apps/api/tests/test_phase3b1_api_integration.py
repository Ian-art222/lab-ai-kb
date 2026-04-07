from __future__ import annotations

from types import SimpleNamespace

from app.api.admin_diagnostics import get_trace, get_traces
from app.api.qa import ask_question
from app.schemas.qa import AskRequest


def test_phase3b1_api_endpoint_chain(monkeypatch):
    trace_store: dict[str, dict] = {}

    monkeypatch.setattr("app.api.qa.ensure_session", lambda *args, **kwargs: SimpleNamespace(id=11))
    monkeypatch.setattr("app.api.qa.append_qa_messages", lambda *args, **kwargs: (SimpleNamespace(id=1), SimpleNamespace(id=2)))
    monkeypatch.setattr("app.api.qa.persist_qa_citations", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.api.qa.mark_last_qa_status", lambda *args, **kwargs: None)

    def _persist_trace(*args, **kwargs):
        meta = kwargs.get("retrieval_meta") or {}
        trace_id = meta.get("trace_id", "trace-default")
        trace_store[trace_id] = {
            "trace_id": trace_id,
            "request_id": meta.get("request_id"),
            "session_id": kwargs.get("session_id"),
            "question": kwargs.get("question"),
            "normalized_query": kwargs.get("question"),
            "rewritten_queries": [kwargs.get("question")],
            "retrieval_strategy": meta.get("retrieval_strategy"),
            "selected_evidence": meta.get("selected_evidence", []),
            "evidence_bundles": meta.get("evidence_bundles", {}),
            "strict_mode": meta.get("strict_mode"),
            "is_abstained": False,
            "failed": False,
            "task_type": meta.get("task_type"),
            "selected_scope": meta.get("selected_scope"),
            "selected_skill": meta.get("selected_skill"),
            "planner_meta": meta.get("planner_meta", {}),
            "workflow_steps": meta.get("workflow_steps_json", []),
            "tool_traces": meta.get("tool_traces_json", []),
            "guardrail_events": [item for item in (meta.get("tool_traces_json") or []) if "guardrail" in str(item.get("tool", ""))],
            "fallback_triggered": meta.get("fallback_triggered"),
            "retrieval_rounds": meta.get("retrieval_rounds"),
            "stop_reason": meta.get("stop_reason"),
            "source_count": meta.get("source_count"),
            "dominant_source_ratio": meta.get("dominant_source_ratio"),
            "multi_source_coverage": meta.get("multi_source_coverage"),
            "compare_result": meta.get("compare_result"),
            "clarification_needed": meta.get("clarification_needed"),
            "debug_json": meta,
            "created_at": "2026-04-07T00:00:00",
            "source_file_ids": [1, 2],
        }

    monkeypatch.setattr("app.api.qa.persist_retrieval_trace", _persist_trace)

    def _run_qa(*args, **kwargs):
        question = kwargs["question"]
        task_type = "simple_qa"
        selected_scope = "default_kb_scope"
        selected_skill = "qa_skill"
        clarification_needed = False
        compare_result = None
        tool_traces = [{"tool": "output_guardrail", "summary": {"triggered": False}}]

        if "比较" in question:
            task_type = "compare"
            selected_skill = "compare_skill"
            compare_result = {
                "comparison_targets": ["A", "B"],
                "side_a_evidence": [{"file_id": 1, "chunk_id": 1}],
                "side_b_evidence": [{"file_id": 2, "chunk_id": 2}],
                "common_points": ["两侧均有证据"],
                "differences": ["差异点1"],
                "conflicts": [],
                "evidence_sufficiency": True,
            }
        if "澄清" in question:
            task_type = "clarification_needed"
            selected_skill = "clarify_skill"
            clarification_needed = True
        if "违规" in question:
            tool_traces = [{"tool": "input_guardrail", "summary": {"triggered": True}}]
        if "文件范围" in question:
            task_type = "collection_scoped_qa"
            selected_scope = "explicit_file_scope"
            selected_skill = "scoped_qa_skill"

        retrieval_meta = {
            "trace_id": f"trace-{abs(hash(question))}",
            "request_id": "req-1",
            "retrieval_strategy": "app_layer_cosine_topk",
            "answer_source": "knowledge_base",
            "scope_type": kwargs.get("scope_type", "all"),
            "strict_mode": True,
            "top_k": 6,
            "min_similarity_score": 0.2,
            "candidate_chunks": 3,
            "matched_chunks": 2,
            "selected_chunks": 2,
            "compatible_file_count": 2,
            "used_file_ids": [1, 2],
            "task_type": task_type,
            "selected_scope": selected_scope,
            "selected_skill": selected_skill,
            "workflow_steps_json": [{"step": "plan_retrieval", "status": "completed"}],
            "tool_traces_json": tool_traces,
            "planner_meta": {"fallback_triggered": False, "retrieval_rounds": 1, "stop_reason": "enough_evidence"},
            "workflow_summary": selected_skill,
            "clarification_needed": clarification_needed,
            "compare_result": compare_result,
            "source_count": 2,
            "dominant_source_ratio": 0.5,
            "multi_source_coverage": 0.67,
            "fallback_triggered": False,
            "retrieval_rounds": 1,
            "stop_reason": "enough_evidence",
        }
        return {
            "answer": "ok",
            "references": [{"file_id": 1, "file_name": "a.md", "chunk_id": 1, "chunk_index": 0, "snippet": "s", "score": 0.9}],
            "references_json": [],
            "evidence_bundles": {"source_count": 1},
            "answer_source": "knowledge_base",
            "used_files": [1],
            "retrieval_meta": retrieval_meta,
            "task_type": task_type,
            "selected_skill": selected_skill,
            "planner_meta": retrieval_meta["planner_meta"],
            "compare_result": compare_result,
            "clarification_needed": clarification_needed,
            "workflow_summary": selected_skill,
        }

    monkeypatch.setattr("app.api.qa.run_qa", _run_qa)
    monkeypatch.setattr("app.api.admin_diagnostics.list_traces", lambda _db, **kwargs: {"total": 1, "limit": 50, "offset": 0, "items": [trace_store[kwargs["trace_id"]]]})
    monkeypatch.setattr("app.api.admin_diagnostics.get_trace_detail", lambda _db, trace_id: trace_store[trace_id])

    user = SimpleNamespace(id=7, role="admin")
    db = SimpleNamespace()

    compare = ask_question(AskRequest(question="请比较A和B", scope_type="all", strict_mode=True, top_k=6), db=db, current_user=user)
    assert compare["task_type"] == "compare"
    assert compare["compare_result"]["side_a_evidence"]
    assert compare["compare_result"]["side_b_evidence"]

    clarify = ask_question(AskRequest(question="这个要先澄清", scope_type="all", strict_mode=True, top_k=6), db=db, current_user=user)
    assert clarify["clarification_needed"] is True

    guardrail = ask_question(AskRequest(question="这是违规输入", scope_type="all", strict_mode=True, top_k=6), db=db, current_user=user)
    guardrail_trace_id = guardrail["retrieval_meta"]["trace_id"]

    scoped = ask_question(AskRequest(question="文件范围问题", scope_type="files", file_ids=[1], strict_mode=True, top_k=6), db=db, current_user=user)
    assert scoped["retrieval_meta"]["selected_scope"] == "explicit_file_scope"

    trace_list = get_traces(trace_id=guardrail_trace_id, db=db, _=user)
    assert trace_list["items"][0]["guardrail_events"]

    detail = get_trace(trace_id=guardrail_trace_id, db=db, _=user)
    assert detail["source_count"] == 2
    assert detail["dominant_source_ratio"] == 0.5
    assert detail["multi_source_coverage"] == 0.67
    assert isinstance(detail["workflow_steps"], list)
