from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from urllib import error, request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 2.5 admin diagnostics smoke flow")
    parser.add_argument("--base-url", default=os.getenv("LAB_AI_KB_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--admin-user", default=os.getenv("LAB_AI_KB_ADMIN_USERNAME", ""))
    parser.add_argument("--admin-pass", default=os.getenv("LAB_AI_KB_ADMIN_PASSWORD", ""))
    parser.add_argument("--member-user", default=os.getenv("LAB_AI_KB_MEMBER_USERNAME", ""))
    parser.add_argument("--member-pass", default=os.getenv("LAB_AI_KB_MEMBER_PASSWORD", ""))
    parser.add_argument("--require-db-env", action="store_true", help="require DATABASE_URL env is set")
    return parser.parse_args()


def log_ok(step: str, msg: str = ""):
    print(f"[OK] {step}{': ' + msg if msg else ''}")


def log_fail(step: str, msg: str):
    print(f"[FAIL] {step}: {msg}")


def http_json(base_url: str, path: str, *, method: str = "GET", token: str | None = None, payload: dict | None = None):
    headers = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = request.Request(f"{base_url}{path}", method=method, headers=headers, data=data)
    try:
        with request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = body
        return exc.code, parsed


def upload_file(base_url: str, token: str, name: str, content: bytes):
    boundary = f"----DiagSmoke{uuid.uuid4().hex}"
    data = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'.encode(),
            b"Content-Type: text/plain\r\n\r\n",
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    req = request.Request(
        f"{base_url}/api/files/upload",
        method="POST",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def expect(step: str, status: int, expected: int):
    if status != expected:
        raise AssertionError(f"{step} expected={expected}, actual={status}")
    log_ok(step, str(status))


def login(base_url: str, username: str, password: str) -> str:
    status, payload = http_json(
        base_url,
        "/api/auth/login",
        method="POST",
        payload={"username": username, "password": password},
    )
    expect(f"login:{username}", status, 200)
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not token:
        raise AssertionError(f"login:{username} missing access_token")
    return str(token)


def main() -> int:
    args = parse_args()
    print(f"Smoke base URL: {args.base_url}")

    if args.require_db_env and not os.getenv("DATABASE_URL"):
        log_fail("env", "DATABASE_URL is required but missing")
        return 2

    status, _ = http_json(args.base_url, "/health")
    if status != 200:
        log_fail("health", f"API not reachable (status={status})")
        return 2
    log_ok("health", "api reachable")

    for key, val in {
        "admin-user": args.admin_user,
        "admin-pass": args.admin_pass,
        "member-user": args.member_user,
        "member-pass": args.member_pass,
    }.items():
        if not val:
            log_fail("credentials", f"missing {key}")
            return 2

    admin_token = login(args.base_url, args.admin_user, args.admin_pass)
    member_token = login(args.base_url, args.member_user, args.member_pass)

    status, _ = http_json(args.base_url, "/api/admin/diagnostics/traces?limit=5", token=member_token)
    expect("member forbidden admin diagnostics", status, 403)

    status, traces = http_json(args.base_url, "/api/admin/diagnostics/traces?limit=5", token=admin_token)
    expect("admin diagnostics traces", status, 200)

    file_id = None
    trace_id = None
    created_session_id = None
    created_file_id = None

    # create trace via upload + index + ask
    up_status, up_payload = upload_file(
        args.base_url,
        member_token,
        "phase25-smoke.txt",
        b"phase25 diagnostics smoke content, code-name amber-fox.",
    )
    expect("upload", up_status, 200)
    created_file_id = int(up_payload["id"])

    ing_status, _ = http_json(
        args.base_url,
        "/api/qa/ingest/file",
        method="POST",
        token=member_token,
        payload={"file_id": created_file_id, "force_reindex": True},
    )
    expect("index submit", ing_status, 200)

    for _ in range(40):
        s, p = http_json(args.base_url, f"/api/qa/files/{created_file_id}/index-status", token=member_token)
        expect("index status", s, 200)
        if p.get("index_status") in {"indexed", "failed"}:
            break
        time.sleep(1)

    qa_status, qa_payload = http_json(
        args.base_url,
        "/api/qa/ask",
        method="POST",
        token=member_token,
        payload={
            "question": "文档中的 code-name 是什么？",
            "scope_type": "files",
            "file_ids": [created_file_id],
            "strict_mode": True,
            "top_k": 4,
        },
    )
    expect("qa ask", qa_status, 200)
    created_session_id = int(qa_payload.get("session_id"))

    status, traces = http_json(args.base_url, "/api/admin/diagnostics/traces?limit=1", token=admin_token)
    expect("trace query", status, 200)
    items = traces.get("items", []) if isinstance(traces, dict) else []
    if not items:
        raise AssertionError("trace query returned empty items")
    trace_id = items[0].get("trace_id")
    if not trace_id:
        raise AssertionError("trace_id missing")

    detail_status, detail_payload = http_json(args.base_url, f"/api/admin/diagnostics/traces/{trace_id}", token=admin_token)
    expect("trace detail", detail_status, 200)

    source_ids = detail_payload.get("source_file_ids", []) if isinstance(detail_payload, dict) else []
    file_id = int(source_ids[0]) if source_ids else created_file_id

    retry_status, _ = http_json(
        args.base_url,
        f"/api/admin/diagnostics/files/{file_id}/retry-index?force_reindex=true",
        token=admin_token,
        method="POST",
    )
    expect("retry-index", retry_status, 200)

    exp_status, _ = http_json(args.base_url, f"/api/admin/diagnostics/traces/{trace_id}/export", token=admin_token)
    expect("trace export", exp_status, 200)

    stats_status, _ = http_json(args.base_url, "/api/admin/diagnostics/traces/stats/reasons", token=admin_token)
    expect("reason stats", stats_status, 200)

    if created_session_id is not None:
        status, _ = http_json(args.base_url, f"/api/qa/sessions/{created_session_id}", method="DELETE", token=member_token)
        expect("cleanup session", status, 200)
    if created_file_id is not None:
        status, _ = http_json(args.base_url, f"/api/files/{created_file_id}", method="DELETE", token=member_token)
        expect("cleanup file", status, 200)

    print("[SUMMARY] Phase2.5 diagnostics smoke PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        log_fail("assertion", str(exc))
        raise SystemExit(1) from exc
