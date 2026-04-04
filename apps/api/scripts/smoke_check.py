from __future__ import annotations

import json
import os
import sys
import time
import uuid
from urllib import error, request


BASE_URL = os.getenv("LAB_AI_KB_BASE_URL", "http://127.0.0.1:8000")
ADMIN_USERNAME = os.getenv("LAB_AI_KB_ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("LAB_AI_KB_ADMIN_PASSWORD", "")
MEMBER_USERNAME = os.getenv("LAB_AI_KB_MEMBER_USERNAME", "")
MEMBER_PASSWORD = os.getenv("LAB_AI_KB_MEMBER_PASSWORD", "")
RUN_FULL_FLOW = os.getenv("LAB_AI_KB_RUN_FULL_FLOW", "0") == "1"
RUN_PROVIDER_TESTS = os.getenv("LAB_AI_KB_RUN_PROVIDER_TESTS", "0") == "1"


def http_json(
    path: str,
    *,
    method: str = "GET",
    token: str | None = None,
    payload: dict | None = None,
) -> tuple[int, dict | list | str]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with request.urlopen(req) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = body
        return exc.code, parsed


def http_multipart_upload(
    path: str,
    *,
    token: str,
    file_name: str,
    file_bytes: bytes,
    folder_id: int | None = None,
) -> tuple[int, dict | list | str]:
    boundary = f"----LabAiKb{uuid.uuid4().hex}"
    body_parts: list[bytes] = []
    if folder_id is not None:
        body_parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                b'Content-Disposition: form-data; name="folder_id"\r\n\r\n',
                str(folder_id).encode(),
                b"\r\n",
            ]
        )
    body_parts.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode(),
            b"Content-Type: text/plain\r\n\r\n",
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    data = b"".join(body_parts)
    req = request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = body
        return exc.code, parsed


def assert_status(name: str, actual: int, expected: int) -> None:
    if actual != expected:
        raise AssertionError(f"{name} failed: expected {expected}, got {actual}")
    print(f"[OK] {name}: {actual}")


def login(username: str, password: str) -> str:
    status, payload = http_json(
        "/api/auth/login",
        method="POST",
        payload={"username": username, "password": password},
    )
    assert_status(f"login:{username}", status, 200)
    if not isinstance(payload, dict) or "access_token" not in payload:
        raise AssertionError(f"login:{username} failed: missing access_token")
    return str(payload["access_token"])


def extract_detail(payload: dict | list | str, fallback: str) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, dict):
            return str(detail.get("message") or fallback)
    if isinstance(payload, str) and payload:
        return payload
    return fallback


def assert_detail_contains(name: str, payload: dict | list | str, expected_substring: str) -> None:
    detail = extract_detail(payload, "")
    if expected_substring not in detail:
        raise AssertionError(
            f"{name} failed: expected detail to contain {expected_substring!r}, actual={detail!r}"
        )
    print(f"[OK] {name}: detail contains {expected_substring!r}")


def poll_index(token: str, file_id: int, timeout_seconds: int = 60) -> dict:
    started = time.time()
    while time.time() - started < timeout_seconds:
        status, payload = http_json(f"/api/qa/files/{file_id}/index-status", token=token)
        assert_status("index status fetch", status, 200)
        if isinstance(payload, dict) and payload.get("index_status") != "indexing":
            return payload
        time.sleep(1)
    raise AssertionError("index polling timed out")


def main() -> int:
    print(f"Smoke check target: {BASE_URL}")

    status, _ = http_json("/api/files")
    assert_status("files requires auth", status, 401)

    admin_token = ""
    member_token = ""
    created_member_session_id: int | None = None

    if MEMBER_USERNAME and MEMBER_PASSWORD:
        member_token = login(MEMBER_USERNAME, MEMBER_PASSWORD)
        status, _ = http_json("/api/users", token=member_token)
        assert_status("member cannot list users", status, 403)

        status, payload = http_json("/api/qa/sessions", token=member_token)
        assert_status("member can list own sessions", status, 200)
        if not isinstance(payload, dict) or "sessions" not in payload:
            raise AssertionError("member session list failed: invalid response")

        status, _ = http_json("/api/settings", token=member_token)
        assert_status("member can read settings", status, 200)

        status, _ = http_json(
            "/api/settings",
            method="PUT",
            token=member_token,
            payload={
                "system_name": "x",
                "lab_name": "x",
                "llm_provider": "openai_compatible",
                "llm_api_base": "",
                "llm_api_key": None,
                "llm_model": "",
                "embedding_provider": "openai_compatible",
                "embedding_api_base": "",
                "embedding_api_key": None,
                "embedding_model": "",
                "embedding_batch_size": None,
                "qa_enabled": False,
                "sidebar_auto_collapse": False,
                "theme_mode": "warm",
            },
        )
        assert_status("member cannot update settings", status, 403)

        status, created_session_payload = http_json(
            "/api/qa/sessions",
            method="POST",
            token=member_token,
        )
        assert_status("member can create session", status, 200)
        if not isinstance(created_session_payload, dict) or "session_id" not in created_session_payload:
            raise AssertionError("member session create failed: invalid response")
        created_member_session_id = int(created_session_payload["session_id"])

    if ADMIN_USERNAME and ADMIN_PASSWORD:
        admin_token = login(ADMIN_USERNAME, ADMIN_PASSWORD)
        status, _ = http_json("/api/users", token=admin_token)
        assert_status("admin can list users", status, 200)

        status, settings_status_payload = http_json("/api/settings/status", token=admin_token)
        assert_status("admin can read settings status", status, 200)
        if not isinstance(settings_status_payload, dict):
            raise AssertionError("settings status invalid: expected object")
        for key in ("current_chat_standard", "current_index_standard", "index_standard_mismatch"):
            if key not in settings_status_payload:
                raise AssertionError(f"settings status missing key: {key}")

        status, settings_payload = http_json("/api/settings", token=admin_token)
        assert_status("admin can read settings", status, 200)
        if not isinstance(settings_payload, dict):
            raise AssertionError("admin settings invalid: expected object")

        status, saved_settings_payload = http_json(
            "/api/settings",
            method="PUT",
            token=admin_token,
            payload={
                "system_name": settings_payload.get("system_name", "实验室知识库"),
                "lab_name": settings_payload.get("lab_name", "实验室内部"),
                "llm_provider": settings_payload.get("llm_provider", "openai_compatible"),
                "llm_api_base": settings_payload.get("llm_api_base", ""),
                "llm_api_key": None,
                "llm_model": settings_payload.get("llm_model", ""),
                "embedding_provider": settings_payload.get("embedding_provider", "openai_compatible"),
                "embedding_api_base": settings_payload.get("embedding_api_base", ""),
                "embedding_api_key": None,
                "embedding_model": settings_payload.get("embedding_model", ""),
                "embedding_batch_size": settings_payload.get("embedding_batch_size"),
                "qa_enabled": settings_payload.get("qa_enabled", False),
                "sidebar_auto_collapse": settings_payload.get("sidebar_auto_collapse", False),
                "theme_mode": settings_payload.get("theme_mode", "warm"),
            },
        )
        assert_status("admin can save settings", status, 200)
        if not isinstance(saved_settings_payload, dict):
            raise AssertionError("saved settings invalid: expected object")

        if RUN_PROVIDER_TESTS and settings_payload.get("llm_api_base") and settings_payload.get("llm_model"):
            status, payload = http_json(
                "/api/settings/test/llm",
                method="POST",
                token=admin_token,
                payload={
                    "provider": settings_payload.get("llm_provider", ""),
                    "api_base": settings_payload.get("llm_api_base", ""),
                    "api_key": "",
                    "model": settings_payload.get("llm_model", ""),
                },
            )
            assert_status("llm test connection", status, 200)
            if not isinstance(payload, dict) or not payload.get("ok"):
                raise AssertionError("llm test connection invalid response")

        if (
            RUN_PROVIDER_TESTS
            and settings_payload.get("embedding_api_base")
            and settings_payload.get("embedding_model")
        ):
            status, payload = http_json(
                "/api/settings/test/embedding",
                method="POST",
                token=admin_token,
                payload={
                    "provider": settings_payload.get("embedding_provider", ""),
                    "api_base": settings_payload.get("embedding_api_base", ""),
                    "api_key": "",
                    "model": settings_payload.get("embedding_model", ""),
                },
            )
            assert_status("embedding test connection", status, 200)
            if not isinstance(payload, dict) or not payload.get("ok"):
                raise AssertionError("embedding test connection invalid response")

    if member_token and admin_token:
        status, session_payload = http_json("/api/qa/sessions", token=member_token)
        assert_status("member session list recheck", status, 200)
        sessions = session_payload.get("sessions", []) if isinstance(session_payload, dict) else []
        if created_member_session_id is not None:
            status, _ = http_json(
                f"/api/qa/sessions/{created_member_session_id}/messages", token=admin_token
            )
            assert_status("admin cannot read member session", status, 404)

    if RUN_FULL_FLOW and member_token:
        smoke_text = (
            "Lab AI KB smoke document.\n"
            "项目代号是 beta-seal。\n"
            "这是一份用于自动化校验的最小文本资料。\n"
        ).encode("utf-8")
        status, upload_payload = http_multipart_upload(
            "/api/files/upload",
            token=member_token,
            file_name="smoke-beta.txt",
            file_bytes=smoke_text,
        )
        assert_status("upload smoke file", status, 200)
        if not isinstance(upload_payload, dict) or "id" not in upload_payload:
            raise AssertionError("upload smoke file failed: missing file id")
        file_id = int(upload_payload["id"])
        status, skipped_upload_payload = http_multipart_upload(
            "/api/files/upload",
            token=member_token,
            file_name="smoke-unindexed.txt",
            file_bytes=b"This file is intentionally left unindexed.\n",
        )
        assert_status("upload unindexed smoke file", status, 200)
        if not isinstance(skipped_upload_payload, dict) or "id" not in skipped_upload_payload:
            raise AssertionError("upload unindexed smoke file failed: missing file id")
        skipped_file_id = int(skipped_upload_payload["id"])

        try:
            status, _ = http_json(
                "/api/qa/ingest/file",
                method="POST",
                token=member_token,
                payload={"file_id": file_id, "force_reindex": True},
            )
            assert_status("submit ingest task", status, 200)

            index_payload = poll_index(member_token, file_id)
            index_status = index_payload.get("index_status")
            if index_status not in {"indexed", "failed"}:
                raise AssertionError(f"unexpected index status: {index_status}")
            print(f"[INFO] final index status: {index_status}")

            status, settings_status_payload = http_json("/api/settings/status", token=member_token)
            assert_status("read settings status for qa flow", status, 200)

            if (
                isinstance(settings_status_payload, dict)
                and settings_status_payload.get("qa_enabled")
                and settings_status_payload.get("llm_configured")
                and settings_status_payload.get("embedding_configured")
                and index_status == "indexed"
            ):
                mixed_scope_session_id: int | None = None
                status, ask_mixed_scope_payload = http_json(
                    "/api/qa/ask",
                    method="POST",
                    token=member_token,
                    payload={
                        "question": "这份资料提到的项目代号是什么？",
                        "scope_type": "files",
                        "file_ids": [file_id, skipped_file_id],
                        "strict_mode": True,
                        "top_k": 4,
                    },
                )
                assert_status("ask mixed indexed and unindexed files", status, 200)
                if not isinstance(ask_mixed_scope_payload, dict) or "session_id" not in ask_mixed_scope_payload:
                    raise AssertionError("ask mixed indexed and unindexed files failed")
                mixed_scope_session_id = int(ask_mixed_scope_payload["session_id"])

                status, no_compatible_payload = http_json(
                    "/api/qa/ask",
                    method="POST",
                    token=member_token,
                    payload={
                        "question": "这份资料提到的项目代号是什么？",
                        "scope_type": "files",
                        "file_ids": [skipped_file_id],
                        "strict_mode": True,
                        "top_k": 4,
                    },
                )
                assert_status("ask only unindexed file returns 400", status, 400)
                assert_detail_contains(
                    "ask only unindexed file detail",
                    no_compatible_payload,
                    "当前范围内没有可用于当前知识库索引标准的已索引文献",
                )

                status, ask_payload = http_json(
                    "/api/qa/ask",
                    method="POST",
                    token=member_token,
                    payload={
                        "question": "这份资料提到的项目代号是什么？",
                        "scope_type": "files",
                        "file_ids": [file_id],
                        "strict_mode": True,
                        "top_k": 4,
                    },
                )
                assert_status("ask smoke question", status, 200)
                if not isinstance(ask_payload, dict) or "session_id" not in ask_payload:
                    raise AssertionError("ask smoke question failed: invalid response")
                session_id = int(ask_payload["session_id"])

                if mixed_scope_session_id is not None:
                    status, _ = http_json(
                        f"/api/qa/sessions/{mixed_scope_session_id}",
                        method="DELETE",
                        token=member_token,
                    )
                    assert_status("delete mixed-scope smoke session", status, 200)

                status, sessions_payload = http_json("/api/qa/sessions", token=member_token)
                assert_status("list sessions after ask", status, 200)
                if not isinstance(sessions_payload, dict) or "sessions" not in sessions_payload:
                    raise AssertionError("session list after ask failed")

                status, _ = http_json(
                    f"/api/qa/sessions/{session_id}",
                    method="DELETE",
                    token=member_token,
                )
                assert_status("delete smoke session", status, 200)
            else:
                print("[INFO] Skip ask/session flow because QA or model settings are not fully enabled.")
        finally:
            status, _ = http_json(f"/api/files/{file_id}", method="DELETE", token=member_token)
            assert_status("delete smoke file", status, 200)
            status, _ = http_json(f"/api/files/{skipped_file_id}", method="DELETE", token=member_token)
            assert_status("delete unindexed smoke file", status, 200)

    if member_token and created_member_session_id is not None:
        status, _ = http_json(
                f"/api/qa/sessions/{created_member_session_id}",
                method="DELETE",
                token=member_token,
        )
        assert_status("delete smoke session", status, 200)

    if not (MEMBER_USERNAME and MEMBER_PASSWORD and ADMIN_USERNAME and ADMIN_PASSWORD):
        print(
            "[INFO] Skip credential-based checks. Set LAB_AI_KB_ADMIN_* and "
            "LAB_AI_KB_MEMBER_* env vars to run full smoke checks."
        )

    print("Smoke check completed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1) from exc
