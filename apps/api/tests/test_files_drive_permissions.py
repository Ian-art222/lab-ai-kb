"""
文件/目录 API 与权限：覆盖网盘场景下的关键边界（SQLite 内存库 + 依赖注入）。
"""
from __future__ import annotations

import os

# 必须在 import app.* 之前，避免 app.db.session 用默认 PostgreSQL DSN 建全局 engine
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

import io
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.files import router as files_router
from app.core.auth import create_access_token
from app.db.session import get_db
from app.models.file_record import FileRecord
from app.models.folder import Folder
from app.models.user import User
from app.services.folder_spaces import ensure_admin_private_folder, ensure_space_roots

mini_app = FastAPI()
mini_app.include_router(files_router)


@pytest.fixture()
def test_db(tmp_path: Path) -> Session:
    # 使用文件型 SQLite，避免 :memory: 在多连接下各自为空库
    db_path = tmp_path / "drive_test.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    # 仅创建文件权限测试所需表，避免 SQLite 无法编译 knowledge 向量列
    with engine.begin() as conn:
        User.__table__.create(conn, checkfirst=True)
        Folder.__table__.create(conn, checkfirst=True)
        FileRecord.__table__.create(conn, checkfirst=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(test_db: Session):
    def _override():
        yield test_db

    mini_app.dependency_overrides[get_db] = _override
    yield TestClient(mini_app)
    mini_app.dependency_overrides.clear()


def _auth(db: Session, user_id: int) -> dict[str, str]:
    user = db.get(User, user_id)
    assert user is not None
    token = create_access_token(user=user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def world(test_db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.api.files.UPLOAD_DIR", tmp_path)
    root = User(
        username="root",
        password_hash="x",
        role="root",
        is_active=True,
        can_download=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    admin_a = User(
        username="admin_a",
        password_hash="x",
        role="admin",
        is_active=True,
        can_download=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    admin_b = User(
        username="admin_b",
        password_hash="x",
        role="admin",
        is_active=True,
        can_download=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    member_ok = User(
        username="mem_ok",
        password_hash="x",
        role="member",
        is_active=True,
        can_download=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    member_no = User(
        username="mem_no",
        password_hash="x",
        role="member",
        is_active=True,
        can_download=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    test_db.add_all([root, admin_a, admin_b, member_ok, member_no])
    test_db.commit()

    home, pub, _prv = ensure_space_roots(test_db)
    own_a = ensure_admin_private_folder(test_db, admin_a)
    own_b = ensure_admin_private_folder(test_db, admin_b)
    assert own_a and own_b

    sub_pub = Folder(
        name="sub_in_public",
        parent_id=pub.id,
        scope="public",
        owner_user_id=None,
        created_at=datetime.utcnow(),
    )
    test_db.add(sub_pub)
    test_db.commit()
    test_db.refresh(sub_pub)

    storage_name = "stor1.bin"
    (tmp_path / storage_name).write_bytes(b"hello")
    f_in_pub = FileRecord(
        file_name="a.txt",
        file_type="txt",
        uploader="admin_a",
        upload_time=datetime.utcnow(),
        folder_id=sub_pub.id,
        storage_path=storage_name,
        file_size=5,
        mime_type="text/plain",
        content_hash="ab" * 16,
        index_status="pending",
    )
    test_db.add(f_in_pub)
    test_db.commit()
    test_db.refresh(f_in_pub)

    return {
        "root": root,
        "admin_a": admin_a,
        "admin_b": admin_b,
        "member_ok": member_ok,
        "member_no": member_no,
        "home": home,
        "pub": pub,
        "sub_pub": sub_pub,
        "own_a": own_a,
        "own_b": own_b,
        "file_pub": f_in_pub,
    }


def test_root_can_create_folder_in_public(client: TestClient, test_db: Session, world):
    h = _auth(test_db, world["root"].id)
    r = client.post(
        "/api/files/folders",
        json={"name": "r_sub", "parent_id": world["pub"].id},
        headers=h,
    )
    assert r.status_code == 200, r.text


def test_admin_cannot_create_folder_in_public(client: TestClient, test_db: Session, world):
    h = _auth(test_db, world["admin_a"].id)
    r = client.post(
        "/api/files/folders",
        json={"name": "illegal", "parent_id": world["pub"].id},
        headers=h,
    )
    assert r.status_code == 403


def test_admin_can_upload_to_public_subfolder(client: TestClient, test_db: Session, world):
    h = _auth(test_db, world["admin_a"].id)
    r = client.post(
        "/api/files/upload",
        data={"folder_id": str(world["sub_pub"].id)},
        files={"file": ("u.bin", io.BytesIO(b"x"), "application/octet-stream")},
        headers=h,
    )
    assert r.status_code == 200, r.text


def test_admin_can_download_public_file(client: TestClient, test_db: Session, world):
    h = _auth(test_db, world["admin_a"].id)
    fid = world["file_pub"].id
    r = client.get(f"/api/files/{fid}/download", headers=h)
    assert r.status_code == 200


def test_admin_can_move_public_file(client: TestClient, test_db: Session, world):
    h = _auth(test_db, world["admin_a"].id)
    fid = world["file_pub"].id
    r = client.patch(
        f"/api/files/{fid}/move",
        json={"folder_id": world["pub"].id},
        headers=h,
    )
    assert r.status_code == 200, r.text


def test_admin_cannot_rename_public_subfolder(client: TestClient, test_db: Session, world):
    h = _auth(test_db, world["admin_a"].id)
    sid = world["sub_pub"].id
    r = client.patch(
        f"/api/files/folders/{sid}/rename",
        json={"name": "renamed"},
        headers=h,
    )
    assert r.status_code == 403


def test_admin_cannot_delete_public_subfolder(client: TestClient, test_db: Session, world):
    h = _auth(test_db, world["admin_a"].id)
    sid = world["sub_pub"].id
    r = client.delete(f"/api/files/folders/{sid}", headers=h)
    assert r.status_code == 403


def test_admin_can_create_folder_in_own_private(client: TestClient, test_db: Session, world):
    h = _auth(test_db, world["admin_a"].id)
    r = client.post(
        "/api/files/folders",
        json={"name": "my_sub", "parent_id": world["own_a"].id},
        headers=h,
    )
    assert r.status_code == 200, r.text


def test_admin_b_cannot_list_admin_a_private_children(client: TestClient, test_db: Session, world):
    h = _auth(test_db, world["admin_b"].id)
    r = client.get(
        "/api/files/folders/children",
        params={"parent_id": world["own_a"].id},
        headers=h,
    )
    assert r.status_code == 403


def test_member_cannot_list_admin_private(client: TestClient, test_db: Session, world):
    h = _auth(test_db, world["member_ok"].id)
    r = client.get(
        "/api/files/folders/children",
        params={"parent_id": world["own_a"].id},
        headers=h,
    )
    assert r.status_code == 403


def test_member_no_download_public_file_fails(client: TestClient, test_db: Session, world):
    h = _auth(test_db, world["member_no"].id)
    fid = world["file_pub"].id
    r = client.get(f"/api/files/{fid}/download", headers=h)
    assert r.status_code == 403


def test_member_ok_download_public_file_ok(client: TestClient, test_db: Session, world):
    h = _auth(test_db, world["member_ok"].id)
    fid = world["file_pub"].id
    r = client.get(f"/api/files/{fid}/download", headers=h)
    assert r.status_code == 200


def test_folder_children_includes_file_caps(client: TestClient, test_db: Session, world):
    h = _auth(test_db, world["admin_a"].id)
    r = client.get(
        "/api/files/folders/children",
        params={"parent_id": world["sub_pub"].id},
        headers=h,
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("space_kind") == "public"
    assert data.get("files")
    f0 = data["files"][0]
    assert f0.get("can_rename") is True
    assert f0.get("can_move") is True


def test_rename_file_api(client: TestClient, test_db: Session, world):
    h = _auth(test_db, world["admin_a"].id)
    fid = world["file_pub"].id
    r = client.patch(
        f"/api/files/{fid}/rename",
        json={"file_name": "b.txt"},
        headers=h,
    )
    assert r.status_code == 200, r.json()["file_name"] == "b.txt"
