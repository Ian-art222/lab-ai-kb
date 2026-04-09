import hashlib
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_root
from app.core.config import settings
from app.core.permissions import (
    can_copy_file,
    can_create_folder_in_parent,
    can_delete_file,
    can_download_file,
    can_download_file_in_folder,
    can_manage_folder_structure,
    can_move_file,
    can_rename_file,
    can_reparent_folder,
    can_upload_file_to_folder,
    can_view_folder,
    is_admin,
    is_member,
    is_root,
    user_effective_can_download,
    user_may_access_file_record,
)
from app.db.session import get_db
from app.models.folder import Folder
from app.models.file_record import FileRecord
from app.models.knowledge import KnowledgeChunk, QAMessage, QASession
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.schemas.file import (
    BatchDownloadRequest,
    ChunkDiagnosticsResponse,
    FileCopyRequest,
    FileItem,
    FileMetaItem,
    FileMoveRequest,
    FileRenameRequest,
)
from app.services import chunk_pipeline
from app.schemas.folder import (
    BreadcrumbItem,
    FolderChildrenResponse,
    FolderCreate,
    FolderItem as FolderItemOut,
    FolderMoveRequest,
    FolderRenameRequest,
    FolderTreeItem,
    FolderViewUi,
)
from app.services.folder_spaces import ensure_space_roots, get_home_root, is_descendant_or_self

router = APIRouter(prefix="/api/files", tags=["files"])

UPLOAD_DIR = Path(settings.upload_dir)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _file_item_dict(
    db: Session,
    user: User,
    file_record: FileRecord,
    folder_name: str | None,
) -> dict:
    """序列化文件条目并附带当前用户在该文件上的能力标记（最终以接口校验为准）。"""
    return {
        "id": file_record.id,
        "file_name": file_record.file_name,
        "file_type": file_record.file_type,
        "uploader": file_record.uploader,
        "upload_time": file_record.upload_time,
        "folder_id": file_record.folder_id,
        "folder_name": folder_name,
        "index_status": file_record.index_status,
        "indexed_at": file_record.indexed_at,
        "index_error": file_record.index_error,
        "index_warning": file_record.index_warning,
        "mime_type": file_record.mime_type,
        "file_size": file_record.file_size,
        "can_download": can_download_file(db, user, file_record),
        "can_rename": can_rename_file(db, user, file_record),
        "can_move": (not is_member(user)) and can_delete_file(db, user, file_record),
        "can_copy": (not is_member(user)) and can_delete_file(db, user, file_record),
        "can_delete": can_delete_file(db, user, file_record),
    }


def _file_item_response(db: Session, user: User, file_record: FileRecord) -> dict:
    folder_name = (
        db.query(Folder.name).filter(Folder.id == file_record.folder_id).scalar()
        if file_record.folder_id is not None
        else None
    )
    return _file_item_dict(db, user, file_record, folder_name)


def _space_hint(
    db: Session,
    user: User,
    current_folder: Folder | None,
) -> tuple[str, str]:
    """返回 (space_kind, space_label) 供前端展示当前所在空间。"""
    home, pub, prv = ensure_space_roots(db)
    if current_folder is None:
        return "home", "全部文件 · home（公共文件夹 / 个人文件夹）"

    cid = current_folder.id
    if cid == pub.id or is_descendant_or_self(db, cid, pub.id):
        return "public", "公共文件夹"

    if cid == prv.id:
        return "private_root", "个人文件夹（入口）"

    if is_descendant_or_self(db, cid, prv.id):
        if getattr(current_folder, "scope", "public") == "admin_private":
            if is_root(user):
                oid = current_folder.owner_user_id
                return "admin_private", f"个人空间（管理员目录 · owner_user_id={oid}）"
            if is_admin(user) and current_folder.owner_user_id == user.id:
                return "admin_private_own", "我的个人文件夹 · 仅您与 root 可访问"
        return "private_tree", "个人文件夹区域"

    return "other", "资料库"


def _folder_to_item_out(db: Session, user: User, folder: Folder) -> FolderItemOut:
    manage = can_manage_folder_structure(db, user, folder)
    return FolderItemOut(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        scope=folder.scope,
        owner_user_id=folder.owner_user_id,
        created_at=folder.created_at,
        can_manage_structure=manage,
        can_open=True,
        can_rename_folder=bool(manage),
        can_delete_folder=bool(manage),
        can_move_folder=bool(manage),
    )


def _get_file_storage_path(file_record: FileRecord) -> Path:
    storage_path = file_record.storage_path or file_record.file_name
    return UPLOAD_DIR / storage_path


def _folder_view_ui(
    db: Session,
    user: User,
    current_folder: Folder | None,
) -> FolderViewUi:
    if current_folder is None:
        return FolderViewUi(
            can_manage_structure=False,
            can_create_subfolder=False,
            can_upload=False,
            can_download_files=user_effective_can_download(user),
            can_move_or_delete_files=not is_member(user),
        )
    return FolderViewUi(
        can_manage_structure=can_manage_folder_structure(db, user, current_folder),
        can_create_subfolder=can_create_folder_in_parent(db, user, current_folder),
        can_upload=can_upload_file_to_folder(db, user, current_folder),
        can_download_files=can_download_file_in_folder(db, user, current_folder.id),
        can_move_or_delete_files=not is_member(user)
        and can_view_folder(db, user, current_folder),
    )


def _visible_folders(db: Session, user: User) -> list[Folder]:
    ensure_space_roots(db)
    all_folders = db.query(Folder).order_by(Folder.id.asc()).all()
    return [f for f in all_folders if can_view_folder(db, user, f)]


def _build_folder_tree(folders: list[Folder]) -> list[dict]:
    by_parent: dict[int | None, list[Folder]] = {}
    for folder in folders:
        by_parent.setdefault(folder.parent_id, []).append(folder)

    for parent_id, items in by_parent.items():
        items.sort(key=lambda x: x.name)

    def build(parent_id: int | None) -> list[dict]:
        children = by_parent.get(parent_id, [])
        return [
            {
                "id": child.id,
                "name": child.name,
                "parent_id": child.parent_id,
                "scope": getattr(child, "scope", "public"),
                "owner_user_id": getattr(child, "owner_user_id", None),
                "can_manage_structure": None,
                "children": build(child.id),
            }
            for child in children
        ]

    # Root nodes are those with parent_id IS NULL
    return build(None)


def _get_breadcrumbs(db: Session, folder: Folder) -> list[BreadcrumbItem]:
    breadcrumbs: list[BreadcrumbItem] = []
    visited: set[int] = set()
    current: Folder | None = folder

    while current is not None and current.id not in visited:
        visited.add(current.id)
        breadcrumbs.append(BreadcrumbItem(id=current.id, name=current.name))

        if current.parent_id is None:
            break

        current = db.query(Folder).filter(Folder.id == current.parent_id).first()

    breadcrumbs.reverse()
    return breadcrumbs


def _get_descendant_ids(db: Session, folder_id: int) -> set[int]:
    descendant_ids: set[int] = set()
    queue: list[int] = [folder_id]

    while queue:
        current_id = queue.pop()
        children = db.query(Folder).filter(Folder.parent_id == current_id).all()
        for child in children:
            if child.id in descendant_ids:
                continue
            descendant_ids.add(child.id)
            queue.append(child.id)

    return descendant_ids


def _check_sibling_name_unique(
    db: Session,
    *,
    folder_id: int,
    parent_id: int | None,
    name: str,
) -> None:
    if parent_id is None:
        existing = (
            db.query(Folder)
            .filter(Folder.parent_id.is_(None), Folder.name == name, Folder.id != folder_id)
            .first()
        )
    else:
        existing = (
            db.query(Folder)
            .filter(
                Folder.parent_id == parent_id,
                Folder.name == name,
                Folder.id != folder_id,
            )
            .first()
        )

    if existing:
        raise HTTPException(status_code=400, detail="同一父目录下名称不能重复")


@router.get("", response_model=list[FileItem])
def get_files(
    q: str | None = None,
    folder_id: int | None = None,
    file_type: str | None = None,
    uploader: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        db.query(FileRecord, Folder.name.label("folder_name"))
        .outerjoin(Folder, FileRecord.folder_id == Folder.id)
    )

    if folder_id is not None:
        query = query.filter(FileRecord.folder_id == folder_id)

    if q:
        query = query.filter(FileRecord.file_name.ilike(f"%{q}%"))

    if file_type:
        query = query.filter(FileRecord.file_type == file_type)

    if uploader:
        # 模糊匹配 uploader，最大程度兼容“字符串输入”
        query = query.filter(FileRecord.uploader.ilike(f"%{uploader}%"))

    query = query.order_by(FileRecord.id.desc())
    rows = query.all()

    out: list[dict] = []
    for file_record, folder_name in rows:
        folder = (
            db.query(Folder).filter(Folder.id == file_record.folder_id).first()
            if file_record.folder_id is not None
            else None
        )
        if folder is None or not can_view_folder(db, current_user, folder):
            continue
        out.append(_file_item_dict(db, current_user, file_record, folder_name))
    return out


@router.get("/dashboard")
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    def _iso_or_none(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    settings = db.query(SystemSetting).filter(SystemSetting.id == 1).first()
    total_files = db.query(func.count(FileRecord.id)).scalar() or 0
    indexed_files = (
        db.query(func.count(FileRecord.id))
        .filter(FileRecord.index_status == "indexed")
        .scalar()
        or 0
    )
    pending_files = (
        db.query(func.count(FileRecord.id))
        .filter(FileRecord.index_status == "pending")
        .scalar()
        or 0
    )
    failed_files = (
        db.query(func.count(FileRecord.id))
        .filter(FileRecord.index_status == "failed")
        .scalar()
        or 0
    )

    recent_rows = (
        db.query(FileRecord, Folder.name.label("folder_name"))
        .outerjoin(Folder, FileRecord.folder_id == Folder.id)
        .order_by(FileRecord.upload_time.desc())
        .limit(5)
        .all()
    )

    recent_files = []
    for file_record, folder_name in recent_rows:
        folder = (
            db.query(Folder).filter(Folder.id == file_record.folder_id).first()
            if file_record.folder_id is not None
            else None
        )
        if folder is None or not can_view_folder(db, current_user, folder):
            continue
        recent_files.append(_file_item_dict(db, current_user, file_record, folder_name))

    recent_indexed_rows = (
        db.query(FileRecord, Folder.name.label("folder_name"))
        .outerjoin(Folder, FileRecord.folder_id == Folder.id)
        .filter(FileRecord.index_status == "indexed", FileRecord.indexed_at.is_not(None))
        .order_by(FileRecord.indexed_at.desc())
        .limit(5)
        .all()
    )
    recent_indexed_files = []
    for file_record, folder_name in recent_indexed_rows:
        folder = (
            db.query(Folder).filter(Folder.id == file_record.folder_id).first()
            if file_record.folder_id is not None
            else None
        )
        if folder is None or not can_view_folder(db, current_user, folder):
            continue
        recent_indexed_files.append(_file_item_dict(db, current_user, file_record, folder_name))

    recent_failed_rows = (
        db.query(FileRecord, Folder.name.label("folder_name"))
        .outerjoin(Folder, FileRecord.folder_id == Folder.id)
        .filter(FileRecord.index_status == "failed")
        .order_by(FileRecord.id.desc())
        .limit(5)
        .all()
    )
    recent_failed_files = []
    for file_record, folder_name in recent_failed_rows:
        folder = (
            db.query(Folder).filter(Folder.id == file_record.folder_id).first()
            if file_record.folder_id is not None
            else None
        )
        if folder is None or not can_view_folder(db, current_user, folder):
            continue
        recent_failed_files.append(_file_item_dict(db, current_user, file_record, folder_name))

    recent_qa_query = (
        db.query(QAMessage, QASession.scope_type)
        .join(QASession, QAMessage.session_id == QASession.id)
        .filter(QAMessage.role == "user")
    )
    if not (is_root(current_user) or is_admin(current_user)):
        recent_qa_query = recent_qa_query.filter(QASession.user_id == current_user.id)
    recent_qa_rows = (
        recent_qa_query.order_by(QAMessage.created_at.desc(), QAMessage.id.desc())
        .limit(5)
        .all()
    )
    recent_qa_records = [
        {
            "id": message.id,
            "session_id": message.session_id,
            "session_title": (
                db.query(QASession.title)
                .filter(QASession.id == message.session_id)
                .scalar()
            ),
            "question": message.content,
            "scope_type": scope_type,
            "created_at": message.created_at.isoformat(),
        }
        for message, scope_type in recent_qa_rows
    ]

    recent_failed_qa_query = (
        db.query(QAMessage, QASession.title)
        .join(QASession, QAMessage.session_id == QASession.id)
        .filter(QAMessage.role == "assistant")
    )
    if not (is_root(current_user) or is_admin(current_user)):
        recent_failed_qa_query = recent_failed_qa_query.filter(
            QASession.user_id == current_user.id
        )
    recent_failed_qa_rows = (
        recent_failed_qa_query.order_by(QAMessage.created_at.desc(), QAMessage.id.desc())
        .limit(20)
        .all()
    )
    recent_failed_qa_records = [
        {
            "id": message.id,
            "session_id": message.session_id,
            "session_title": session_title,
            "error": message.content,
            "created_at": message.created_at.isoformat(),
        }
        for message, session_title in recent_failed_qa_rows
        if isinstance(message.references_json, dict)
        and message.references_json.get("kind") == "error"
    ][:5]

    activity_points = [
        settings.last_qa_at if settings else None,
        settings.last_llm_test_at if settings else None,
        settings.last_embedding_test_at if settings else None,
        recent_rows[0][0].upload_time if recent_rows else None,
        recent_indexed_rows[0][0].indexed_at if recent_indexed_rows and recent_indexed_rows[0][0].indexed_at else None,
        recent_failed_rows[0][0].upload_time if recent_failed_rows else None,
    ]
    latest_activity = max((point for point in activity_points if point is not None), default=None)

    return {
        "summary": {
            "total_files": total_files,
            "indexed_files": indexed_files,
            "pending_files": pending_files,
            "failed_files": failed_files,
        },
        "recent_files": recent_files,
        "recent_indexed_files": recent_indexed_files,
        "recent_failed_files": recent_failed_files,
        "recent_qa_records": recent_qa_records,
        "ops_status": {
            "qa_enabled": bool(settings.qa_enabled) if settings else False,
            "llm_configured": bool(
                settings
                and settings.llm_api_base
                and settings.llm_api_key
                and settings.llm_model
            ),
            "embedding_configured": bool(
                settings
                and settings.embedding_api_base
                and settings.embedding_api_key
                and settings.embedding_model
            ),
            "last_qa_success": settings.last_qa_success if settings else None,
            "last_qa_at": _iso_or_none(settings.last_qa_at if settings else None),
            "last_qa_error": settings.last_qa_error if settings else None,
            "last_llm_test_success": settings.last_llm_test_success if settings else None,
            "last_llm_test_at": _iso_or_none(settings.last_llm_test_at if settings else None),
            "last_llm_test_detail": settings.last_llm_test_detail if settings else None,
            "last_embedding_test_success": settings.last_embedding_test_success if settings else None,
            "last_embedding_test_at": _iso_or_none(settings.last_embedding_test_at if settings else None),
            "last_embedding_test_detail": settings.last_embedding_test_detail if settings else None,
            "last_activity_at": _iso_or_none(latest_activity),
        },
        "recent_failed_qa_records": recent_failed_qa_records,
    }


@router.get("/folders", response_model=list[FolderTreeItem])
def get_folders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    返回真正的目录树（根目录 parent_id = NULL）。

    注意：相较旧版本（扁平列表），这里返回结构发生变化，
    每个节点包含 `children` 字段。
    """
    get_home_root(db)
    folders = _visible_folders(db, current_user)
    folders.sort(key=lambda x: x.name)
    return _build_folder_tree(folders)


def _new_folder_scope_owner(parent: Folder) -> tuple[str, int | None]:
    if getattr(parent, "scope", "public") == "admin_private":
        return "admin_private", parent.owner_user_id
    return "public", None


@router.post("/folders", response_model=FolderItemOut)
def create_folder(
    data: FolderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    name = data.name.strip()
    parent_id = data.parent_id

    if not name:
        raise HTTPException(status_code=400, detail="文件夹名称不能为空")

    home_root = get_home_root(db)
    ensure_space_roots(db)

    if parent_id is None:
        parent_id = home_root.id

    parent = db.query(Folder).filter(Folder.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=400, detail="目标父目录不存在")

    if not can_create_folder_in_parent(db, current_user, parent):
        raise HTTPException(status_code=403, detail="无权在此路径下创建目录")

    existing = (
        db.query(Folder)
        .filter(Folder.parent_id == parent_id, Folder.name == name)
        .first()
    )

    if existing:
        raise HTTPException(status_code=400, detail="同一父目录下名称不能重复")

    scope, owner_id = _new_folder_scope_owner(parent)
    folder = Folder(
        name=name,
        parent_id=parent_id,
        scope=scope,
        owner_user_id=owner_id,
        created_at=datetime.utcnow(),
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return _folder_to_item_out(db, current_user, folder)


@router.get("/folders/children", response_model=FolderChildrenResponse)
def get_folder_children(
    parent_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    home_root = get_home_root(db)
    ensure_space_roots(db)
    home_id = home_root.id

    if not can_view_folder(db, current_user, home_root):
        raise HTTPException(status_code=403, detail="无权浏览此目录")

    if parent_id is None or parent_id == home_id:
        current_folder = None
        breadcrumbs = []
        raw_folders = (
            db.query(Folder)
            .filter(Folder.parent_id == home_id)
            .order_by(Folder.name.asc())
            .all()
        )
        folders = [f for f in raw_folders if can_view_folder(db, current_user, f)]
        rows = (
            db.query(FileRecord, Folder.name.label("folder_name"))
            .outerjoin(Folder, FileRecord.folder_id == Folder.id)
            .filter(FileRecord.folder_id == home_id)
            .order_by(FileRecord.id.desc())
            .all()
        )
        ui = _folder_view_ui(db, current_user, None)
    else:
        current_folder = db.query(Folder).filter(Folder.id == parent_id).first()
        if not current_folder:
            raise HTTPException(status_code=404, detail="目录不存在")
        if not can_view_folder(db, current_user, current_folder):
            raise HTTPException(status_code=403, detail="无权浏览此目录")

        breadcrumbs = _get_breadcrumbs(db, current_folder)
        breadcrumbs = [b for b in breadcrumbs if b.id != home_id]

        raw_folders = (
            db.query(Folder)
            .filter(Folder.parent_id == parent_id)
            .order_by(Folder.name.asc())
            .all()
        )
        folders = [f for f in raw_folders if can_view_folder(db, current_user, f)]
        rows = (
            db.query(FileRecord, Folder.name.label("folder_name"))
            .outerjoin(Folder, FileRecord.folder_id == Folder.id)
            .filter(FileRecord.folder_id == parent_id)
            .order_by(FileRecord.id.desc())
            .all()
        )
        ui = _folder_view_ui(db, current_user, current_folder)

    files: list[dict] = []
    for file_record, folder_name in rows:
        fobj = (
            db.query(Folder).filter(Folder.id == file_record.folder_id).first()
            if file_record.folder_id is not None
            else None
        )
        if fobj is None or not can_view_folder(db, current_user, fobj):
            continue
        files.append(_file_item_dict(db, current_user, file_record, folder_name))

    folder_items = [_folder_to_item_out(db, current_user, f) for f in folders]

    sk, sl = _space_hint(db, current_user, current_folder)
    return {
        "current_folder": (
            None if current_folder is None else _folder_to_item_out(db, current_user, current_folder)
        ),
        "breadcrumbs": breadcrumbs,
        "folders": folder_items,
        "files": files,
        "ui": ui,
        "space_kind": sk,
        "space_label": sl,
    }


@router.patch("/folders/{folder_id}/rename", response_model=FolderItemOut)
def rename_folder(
    folder_id: int,
    data: FolderRenameRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder = db.query(Folder).filter(Folder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="目录不存在")

    if not can_manage_folder_structure(db, current_user, folder):
        raise HTTPException(status_code=403, detail="无权重命名此目录")

    if folder.parent_id is None:
        raise HTTPException(
            status_code=400,
            detail="根目录 home 不允许重命名",
        )

    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="文件夹名称不能为空")

    _check_sibling_name_unique(
        db,
        folder_id=folder_id,
        parent_id=folder.parent_id,
        name=name,
    )

    folder.name = name
    db.commit()
    db.refresh(folder)
    return _folder_to_item_out(db, current_user, folder)


@router.patch("/folders/{folder_id}/move", response_model=FolderItemOut)
def move_folder(
    folder_id: int,
    data: FolderMoveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder = db.query(Folder).filter(Folder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="目录不存在")

    if folder.parent_id is None:
        raise HTTPException(status_code=400, detail="根目录 home 不允许移动")

    home_root = get_home_root(db)

    # folder_id=NULL 在语义上表示“移动到 home”，不会生成新的 parent_id=NULL 根目录
    new_parent_id = data.parent_id
    if new_parent_id is None:
        new_parent_id = home_root.id

    if new_parent_id == folder_id:
        raise HTTPException(status_code=400, detail="不能移动到自己")

    new_parent = db.query(Folder).filter(Folder.id == new_parent_id).first()
    if not new_parent:
        raise HTTPException(status_code=404, detail="目标父目录不存在")

    if not can_reparent_folder(db, current_user, folder, new_parent):
        raise HTTPException(status_code=403, detail="无权移动此目录")

    # 不能移动到自己的任意后代，避免制造循环
    descendant_ids = _get_descendant_ids(db, folder_id)
    if new_parent_id in descendant_ids:
        raise HTTPException(status_code=400, detail="不能移动到自己的子孙目录")

    # 检查同一目标父目录下重名（根目录同样要在 API 层保证唯一）
    _check_sibling_name_unique(
        db,
        folder_id=folder_id,
        parent_id=new_parent_id,
        name=folder.name,
    )

    folder.parent_id = new_parent_id
    db.commit()
    db.refresh(folder)
    return _folder_to_item_out(db, current_user, folder)


@router.delete("/folders/{folder_id}")
def delete_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder = db.query(Folder).filter(Folder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="目录不存在")

    if not can_manage_folder_structure(db, current_user, folder):
        raise HTTPException(status_code=403, detail="无权删除此目录")

    if folder.parent_id is None:
        raise HTTPException(status_code=400, detail="根目录 home 不允许删除")

    # 第一轮只允许删除空目录（不递归）
    has_child_folders = (
        db.query(Folder).filter(Folder.parent_id == folder_id).first() is not None
    )
    has_files = (
        db.query(FileRecord).filter(FileRecord.folder_id == folder_id).first()
        is not None
    )

    if has_child_folders or has_files:
        raise HTTPException(status_code=400, detail="目录非空，不能删除")

    db.delete(folder)
    db.commit()
    return {"message": "删除成功"}


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder_id: int | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名无效")

    get_home_root(db)
    _, pub_root, _ = ensure_space_roots(db)

    if folder_id is None:
        folder_id = pub_root.id

    folder = db.query(Folder).filter(Folder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=400, detail="文件夹不存在")
    if not can_upload_file_to_folder(db, current_user, folder):
        raise HTTPException(status_code=403, detail="无权上传到该目录")

    file_name = file.filename
    file_ext = file_name.split(".")[-1].lower() if "." in file_name else "unknown"
    content = await file.read()
    content_hash = hashlib.sha256(content).hexdigest()
    suffix = Path(file_name).suffix
    storage_name = f"{uuid4().hex}{suffix}"
    save_path = UPLOAD_DIR / storage_name
    save_path.write_bytes(content)

    new_file = FileRecord(
        file_name=file_name,
        file_type=file_ext,
        uploader=current_user.username,
        upload_time=datetime.utcnow(),
        folder_id=folder_id,
        storage_path=storage_name,
        file_size=len(content),
        mime_type=file.content_type,
        content_hash=content_hash,
        index_status="pending",
    )

    db.add(new_file)
    db.commit()
    db.refresh(new_file)

    return {
        "message": "上传成功",
        "id": new_file.id,
        "file_name": new_file.file_name,
    }


@router.get("/{file_id}/download")
def download_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()

    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    if not can_download_file(db, current_user, file_record):
        raise HTTPException(status_code=403, detail="无权下载该文件")

    file_path = _get_file_storage_path(file_record)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="服务器上未找到该文件")

    return FileResponse(
        path=file_path,
        filename=file_record.file_name,
        media_type="application/octet-stream",
    )


@router.post("/batch-download")
def batch_download_files(
    payload: BatchDownloadRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deduped_ids = list(dict.fromkeys(payload.file_ids or []))
    if not deduped_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个文件")

    file_records = (
        db.query(FileRecord)
        .filter(FileRecord.id.in_(deduped_ids))
        .all()
    )
    file_records.sort(key=lambda record: deduped_ids.index(record.id))
    found_ids = {record.id for record in file_records}
    missing_ids = [fid for fid in deduped_ids if fid not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"文件不存在: {missing_ids}")

    for file_record in file_records:
        if not can_download_file(db, current_user, file_record):
            raise HTTPException(status_code=403, detail="批量下载包含无权下载的文件")

    file_infos: list[tuple[FileRecord, Path]] = []
    for file_record in file_records:
        file_path = _get_file_storage_path(file_record)
        if not file_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"服务器上未找到文件: {file_record.file_name}",
            )
        file_infos.append((file_record, file_path))

    tmp_file = tempfile.NamedTemporaryFile(prefix="lab-ai-kb-batch-", suffix=".zip", delete=False)
    zip_path = Path(tmp_file.name)
    tmp_file.close()

    try:
        with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zipf:
            used_names: set[str] = set()
            for file_record, file_path in file_infos:
                arc_name = file_record.file_name
                if arc_name in used_names:
                    stem = Path(arc_name).stem
                    suffix = Path(arc_name).suffix
                    arc_name = f"{stem}-{file_record.id}{suffix}"
                used_names.add(arc_name)
                zipf.write(file_path, arcname=arc_name)

        zip_size = zip_path.stat().st_size
        filename = f"files-batch-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.zip"

        def _cleanup(path: Path):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass

        background_tasks.add_task(_cleanup, zip_path)

        return FileResponse(
            path=zip_path,
            filename=filename,
            media_type="application/zip",
            headers={"Content-Length": str(zip_size)},
        )
    except Exception:
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)
        raise


@router.patch("/{file_id}/move", response_model=FileItem)
def move_file(
    file_id: int,
    data: FileMoveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    get_home_root(db)
    _, pub_root, _ = ensure_space_roots(db)

    new_folder_id = data.folder_id
    if new_folder_id is None:
        new_folder_id = pub_root.id

    folder = db.query(Folder).filter(Folder.id == new_folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="目标目录不存在")

    if not can_move_file(db, current_user, file_record, folder):
        raise HTTPException(status_code=403, detail="无权移动该文件")

    # 同一目标目录下不允许与已有文件同名
    existing = (
        db.query(FileRecord)
        .filter(
            FileRecord.folder_id == new_folder_id,
            FileRecord.file_name == file_record.file_name,
            FileRecord.id != file_id,
        )
        .first()
    )

    if existing:
        raise HTTPException(status_code=400, detail="目标目录下已存在同名文件")

    file_record.folder_id = new_folder_id
    db.commit()
    db.refresh(file_record)

    return _file_item_response(db, current_user, file_record)


@router.patch("/{file_id}/rename", response_model=FileItem)
def rename_file_record(
    file_id: int,
    data: FileRenameRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")
    if not can_rename_file(db, current_user, file_record):
        raise HTTPException(status_code=403, detail="无权重命名该文件")

    name = data.file_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    existing = (
        db.query(FileRecord)
        .filter(
            FileRecord.folder_id == file_record.folder_id,
            FileRecord.file_name == name,
            FileRecord.id != file_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="同目录下已存在同名文件")

    file_record.file_name = name
    db.commit()
    db.refresh(file_record)
    return _file_item_response(db, current_user, file_record)


@router.post("/{file_id}/copy", response_model=FileItem)
def copy_file_record(
    file_id: int,
    data: FileCopyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    get_home_root(db)
    _, pub_root, _ = ensure_space_roots(db)
    dest_folder_id = data.folder_id if data.folder_id is not None else pub_root.id
    dest_folder = db.query(Folder).filter(Folder.id == dest_folder_id).first()
    if not dest_folder:
        raise HTTPException(status_code=404, detail="目标目录不存在")

    if not can_copy_file(db, current_user, file_record, dest_folder):
        raise HTTPException(status_code=403, detail="无权复制该文件")

    src_path = _get_file_storage_path(file_record)
    if not src_path.exists():
        raise HTTPException(status_code=404, detail="服务器上未找到该文件")

    existing = (
        db.query(FileRecord)
        .filter(
            FileRecord.folder_id == dest_folder_id,
            FileRecord.file_name == file_record.file_name,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="目标目录下已存在同名文件")

    suffix = Path(file_record.file_name).suffix
    storage_name = f"{uuid4().hex}{suffix}"
    dest_path = UPLOAD_DIR / storage_name
    shutil.copy2(src_path, dest_path)

    new_file = FileRecord(
        file_name=file_record.file_name,
        file_type=file_record.file_type,
        uploader=current_user.username,
        upload_time=datetime.utcnow(),
        folder_id=dest_folder_id,
        storage_path=storage_name,
        file_size=dest_path.stat().st_size,
        mime_type=file_record.mime_type,
        content_hash=file_record.content_hash,
        index_status="pending",
    )
    db.add(new_file)
    db.commit()
    db.refresh(new_file)

    return _file_item_response(db, current_user, new_file)


@router.delete("/{file_id}")
def delete_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    if not can_delete_file(db, current_user, file_record):
        raise HTTPException(status_code=403, detail="无权删除该文件")

    file_path = _get_file_storage_path(file_record)

    # 先删 DB 记录，保证后续下载/列表不会再引用这条元数据
    db.delete(file_record)
    db.commit()

    # 再尝试删除磁盘文件；即使文件不存在也要忽略
    try:
        if file_path.exists():
            file_path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        # 磁盘删除失败不影响已删除的 DB 记录
        pass

    return {"message": "删除成功"}


@router.get("/{file_id}/meta", response_model=FileMetaItem)
def file_meta(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = (
        db.query(FileRecord, Folder.name.label("folder_name"))
        .outerjoin(Folder, FileRecord.folder_id == Folder.id)
        .filter(FileRecord.id == file_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="文件不存在")

    file_record, folder_name = row
    if not user_may_access_file_record(db, current_user, file_record):
        raise HTTPException(status_code=403, detail="无权查看该文件")
    file_path = _get_file_storage_path(file_record)

    size: int | None
    if file_path.exists():
        try:
            size = file_path.stat().st_size
        except OSError:
            size = file_record.file_size
    else:
        size = file_record.file_size

    return {
        "id": file_record.id,
        "file_name": file_record.file_name,
        "file_type": file_record.file_type,
        "uploader": file_record.uploader,
        "upload_time": file_record.upload_time,
        "folder_id": file_record.folder_id,
        "folder_name": folder_name,
        "size": size,
        "index_status": file_record.index_status,
        "indexed_at": file_record.indexed_at,
        "index_error": file_record.index_error,
        "index_warning": file_record.index_warning,
        "mime_type": file_record.mime_type,
        "content_hash": file_record.content_hash,
        "file_size": file_record.file_size,
    }


@router.get("/{file_id}/chunk-diagnostics", response_model=ChunkDiagnosticsResponse)
def file_chunk_diagnostics(
    file_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_root),
):
    """索引 chunk 分布统计（parent/child、长度分位、block_type），用于调参与质量观测。"""
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

    chunks = (
        db.query(KnowledgeChunk)
        .filter(KnowledgeChunk.file_id == file_id)
        .order_by(KnowledgeChunk.chunk_index.asc())
        .all()
    )
    parents = [c for c in chunks if c.chunk_kind == "parent"]
    children = [c for c in chunks if c.chunk_kind == "child"]
    legacy = [c for c in chunks if c.chunk_kind is None]

    child_lens = [len((c.content or "")) for c in children]
    child_tokens = [c.token_count for c in children if c.token_count is not None]

    def _percentile(sorted_vals: list[int], p: float) -> int | None:
        if not sorted_vals:
            return None
        idx = min(len(sorted_vals) - 1, int(len(sorted_vals) * p))
        return sorted_vals[idx]

    sl = sorted(child_lens)
    short_thr = 200
    long_thr = 800
    short_r = sum(1 for x in child_lens if x < short_thr) / len(child_lens) if child_lens else 0.0
    long_r = sum(1 for x in child_lens if x > long_thr) / len(child_lens) if child_lens else 0.0

    bt_counts: dict[str, int] = {}
    parent_bt: dict[str, int] = {}
    max_depth = 0
    for c in children:
        meta = c.metadata_json if isinstance(c.metadata_json, dict) else {}
        bt = str(meta.get("block_type") or "unknown")
        bt_counts[bt] = bt_counts.get(bt, 0) + 1
        sp = meta.get("section_path")
        if isinstance(sp, list) and sp:
            max_depth = max(max_depth, len(sp))
        elif meta.get("heading_path"):
            hp = str(meta.get("heading_path") or "")
            if hp:
                max_depth = max(max_depth, hp.count(">") + 1)

    for p in parents:
        meta = p.metadata_json if isinstance(p.metadata_json, dict) else {}
        bt = str(meta.get("block_type") or "parent")
        parent_bt[bt] = parent_bt.get(bt, 0) + 1
        sp = meta.get("section_path")
        if isinstance(sp, list) and sp:
            max_depth = max(max_depth, len(sp))

    special_keys = ("table", "list", "faq_pair", "code", "heading", "paragraph", "mixed")
    special = {k: bt_counts.get(k, 0) for k in special_keys if bt_counts.get(k, 0)}

    return ChunkDiagnosticsResponse(
        file_id=file_id,
        file_name=file_record.file_name,
        index_status=file_record.index_status,
        pipeline_version=file_record.pipeline_version,
        parent_count=len(parents),
        child_count=len(children),
        legacy_count=len(legacy),
        total_rows=len(chunks),
        avg_child_token_count=(sum(child_tokens) / len(child_tokens)) if child_tokens else None,
        avg_child_char_count=(sum(child_lens) / len(child_lens)) if child_lens else None,
        p50_child_char=_percentile(sl, 0.5),
        p90_child_char=_percentile(sl, 0.9),
        short_child_ratio=short_r,
        long_child_ratio=long_r,
        block_type_counts=bt_counts,
        extractor_version=settings.ingest_extractor_version,
        extractor_rules_version=chunk_pipeline.EXTRACTOR_RULES_VERSION,
        parent_block_type_counts=parent_bt,
        max_heading_depth=max_depth,
        special_block_counts=special,
    )
