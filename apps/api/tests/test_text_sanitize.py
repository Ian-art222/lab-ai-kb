from app.services.text_sanitize import (
    sanitize_json_for_db,
    sanitize_rows_spec_for_db,
    sanitize_text_for_db,
)


def test_sanitize_text_removes_nul():
    assert "\x00" not in sanitize_text_for_db("Sa\x00ower")
    assert sanitize_text_for_db("a\u0000b") == "ab"


def test_sanitize_json_nested():
    raw = {"a": "x\x00y", "b": [{"c": "\x00"}]}
    out = sanitize_json_for_db(raw)
    assert out["a"] == "xy"
    assert out["b"][0]["c"] == ""


def test_sanitize_rows_spec_metadata_and_content_hash():
    rows = [
        {
            "chunk_kind": "child",
            "parent_ref": 0,
            "content": "hello\x00world",
            "chunk_index": 1,
            "page_number": 1,
            "section_title": "t\x00",
            "metadata_json": {"content_hash": "old", "filename": "f\x00.pdf"},
        }
    ]
    out = sanitize_rows_spec_for_db(rows)
    assert out[0]["content"] == "helloworld"
    assert "\x00" not in out[0]["metadata_json"]["filename"]
    assert out[0]["metadata_json"]["content_hash"] != "old"
