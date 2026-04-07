from __future__ import annotations

from app.services import diagnostics_service


class _FakeTraceQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def group_by(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *_args, **_kwargs):
        return _FakeTraceQuery(self._rows)


def test_extract_source_file_ids_from_evidence_and_bundles():
    selected = [{"file_id": 11}, {"source_file_id": "12"}, {"file_id": 11}]
    bundles = {"primary": [{"file_id": 13}], "extra": {"source_file_id": 14}}
    result = diagnostics_service._extract_source_file_ids(selected, bundles)
    assert result == [11, 12, 13, 14]


def test_list_reason_code_stats():
    db = _FakeDB(rows=[("low_retrieval_confidence", 3), ("internal_error", 1), (None, 9)])
    result = diagnostics_service.list_reason_code_stats(db)
    assert result == [
        {"reason_code": "low_retrieval_confidence", "count": 3},
        {"reason_code": "internal_error", "count": 1},
    ]


def test_export_trace(monkeypatch):
    monkeypatch.setattr(
        diagnostics_service,
        "get_trace_detail",
        lambda *_args, **_kwargs: {
            "trace_id": "trace-export",
            "request_id": "req",
            "session_id": 3,
            "question": "q",
            "is_abstained": False,
            "failed": False,
            "created_at": "2026-04-01T00:00:00",
            "source_file_ids": [5],
        },
    )

    payload = diagnostics_service.export_trace(db=None, trace_id="trace-export")
    assert payload["trace"]["trace_id"] == "trace-export"
    assert payload["source_file_ids"] == [5]
