from pathlib import Path

import app.services.failure_cases as failure_cases


def test_build_failure_case_shape():
    payload = failure_cases.build_failure_case(
        query="q",
        trace_id="t1",
        request_id="r1",
        reason_code="internal_error",
        answer_summary="summary",
        retrieved_refs=[{"file_id": 1}],
    )
    assert payload["query"] == "q"
    assert payload["trace_id"] == "t1"
    assert payload["reason_code"] == "internal_error"
    assert isinstance(payload["retrieved_refs"], list)
    assert "created_at" in payload


def test_sink_failure_case_best_effort(tmp_path):
    old_dir = failure_cases.settings.qa_failure_cases_dir
    try:
        failure_cases.settings.qa_failure_cases_dir = str(tmp_path / "sink")
        failure_cases.sink_failure_case({"k": "v"})
        out = Path(failure_cases.settings.qa_failure_cases_dir) / "qa_failure_cases.jsonl"
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert '"k": "v"' in content
    finally:
        failure_cases.settings.qa_failure_cases_dir = old_dir
