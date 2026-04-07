import hashlib
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.folder import Folder
from app.models.file_record import FileRecord
from app.models.knowledge import QAMessage, QASession
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.schemas.file import BatchDownloadRequest, FileItem, FileMetaItem, FileMoveRequest
from app.schemas.folder import (
    BreadcrumbItem,
    FolderChildrenResponse,
    FolderCreate,
    FolderItem,
    FolderMoveRequest,
    FolderRenameRequest,
    FolderTreeItem,
)

router = APIRouter(prefix="/api/files", tags=["files"])

UPLOAD_DIR = Path(settings.upload_dir)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

HOME_NAME = "home"


def _serialize_file_item(file_record: FileRecord, folder_name: str | None) -> dict:
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
        "retry_count": file_record.retry_count,
        "last_error_code": file_record.last_error_code,
        "pipeline_version": file_record.pipeline_version,
    }


def _get_file_storage_path(file_record: FileRecord) -> Path:
    storage_path = file_record.storage_path or file_record.file_name
    return UPLOAD_DIR / storage_path


def _get_home_root(db: Session) -> Folder:
    """
    获取唯一 home 根目录。
    通过 API 层额外兜底，避免因历史数据导致多个 parent_id=NULL 的根目录。
    """
    root = (
        db.query(Folder)
        .filter(Folder.parent_id.is_(None))
        .order_by(Folder.id.asc())
        .first()
    )

    if root is None:
        # 理论上迁移已创建；这里兜底确保接口不会因数据库缺失而报错
        root = Folder(name=HOME_NAME, parent_id=None, created_at=datetime.utcnow())
        db.add(root)
        db.commit()
        db.refresh(root)

    if root.name != HOME_NAME:
        root.name = HOME_NAME
        db.commit()
        db.refresh(root)

    return root

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

    return [_serialize_file_item(file_record, folder_name) for file_record, folder_name in rows]


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

    recent_files = [_serialize_file_item(file_record, folder_name) for file_record, folder_name in recent_rows]

    recent_indexed_rows = (
        db.query(FileRecord, Folder.name.label("folder_name"))
        .outerjoin(Folder, FileRecord.folder_id == Folder.id)
        .filter(FileRecord.index_status == "indexed", FileRecord.indexed_at.is_not(None))
        .order_by(FileRecord.indexed_at.desc())
        .limit(5)
        .all()
    )
    recent_indexed_files = [_serialize_file_item(file_record, folder_name) for file_record, folder_name in recent_indexed_rows]

    recent_failed_rows = (
        db.query(FileRecord, Folder.name.label("folder_name"))
        .outerjoin(Folder, FileRecord.folder_id == Folder.id)
        .filter(FileRecord.index_status == "failed")
        .order_by(FileRecord.id.desc())
        .limit(5)
        .all()
    )
    recent_failed_files = [_serialize_file_item(file_record, folder_name) for file_record, folder_name in recent_failed_rows]

    recent_qa_query = (
        db.query(QAMessage, QASession.scope_type)
        .join(QASession, QAMessage.session_id == QASession.id)
        .filter(QAMessage.role == "user")
    )
    if current_user.role != "admin":
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
    if current_user.role != "admin":
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
    # 触发兜底：确保 parent_id=NULL 的根目录名字始终为 home
    _get_home_root(db)

    folders = db.query(Folder).order_by(Folder.name.asc()).all()
    return _build_folder_tree(folders)


@router.post("/folders", response_model=FolderItem)
def create_folder(
    data: FolderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    name = data.name.strip()
    parent_id = data.parent_id

    if not name:
        raise HTTPException(status_code=400, detail="文件夹名称不能为空")

    home_root = _get_home_root(db)

    # 禁止通过 API 创建新的根目录：parent_id=NULL 统一挂到 home 下
    if parent_id is None:
        parent_id = home_root.id
    else:
        parent = db.query(Folder).filter(Folder.id == parent_id).first()
        if not parent:
            raise HTTPException(status_code=400, detail="目标父目录不存在")

    existing = (
        db.query(Folder)
        .filter(Folder.parent_id == parent_id, Folder.name == name)
        .first()
    )

    if existing:
        raise HTTPException(status_code=400, detail="同一父目录下名称不能重复")

    folder = Folder(name=name, parent_id=parent_id, created_at=datetime.utcnow())
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


@router.get("/folders/children", response_model=FolderChildrenResponse)
def get_folder_children(
    parent_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    home_root = _get_home_root(db)
    home_id = home_root.id

    # 根目录容器（前端传 null）与真实 home 根节点（parent_id == home_id）
    # 在展示语义上保持一致：展示 home 的直接子目录与文件。
    if parent_id is None or parent_id == home_id:
        current_folder = None
        breadcrumbs: list[BreadcrumbItem] = []
        folders = (
            db.query(Folder)
            .filter(Folder.parent_id == home_id)
            .order_by(Folder.name.asc())
            .all()
        )
        rows = (
            db.query(FileRecord, Folder.name.label("folder_name"))
            .outerjoin(Folder, FileRecord.folder_id == Folder.id)
            .filter(FileRecord.folder_id == home_id)
            .order_by(FileRecord.id.desc())
            .all()
        )
    else:
        current_folder = db.query(Folder).filter(Folder.id == parent_id).first()
        if not current_folder:
            raise HTTPException(status_code=404, detail="目录不存在")

        breadcrumbs = _get_breadcrumbs(db, current_folder)
        # 前端面包屑里已经有固定 home 起点，去掉 home 根节点避免重复展示
        breadcrumbs = [b for b in breadcrumbs if b.id != home_id]

        folders = (
            db.query(Folder)
            .filter(Folder.parent_id == parent_id)
            .order_by(Folder.name.asc())
            .all()
        )
        rows = (
            db.query(FileRecord, Folder.name.label("folder_name"))
            .outerjoin(Folder, FileRecord.folder_id == Folder.id)
            .filter(FileRecord.folder_id == parent_id)
            .order_by(FileRecord.id.desc())
            .all()
        )

    files = [_serialize_file_item(file_record, folder_name) for file_record, folder_name in rows]

    return {
        "current_folder": current_folder,
        "breadcrumbs": breadcrumbs,
        "folders": folders,
        "files": files,
    }


@router.patch("/folders/{folder_id}/rename", response_model=FolderItem)
def rename_folder(
    folder_id: int,
    data: FolderRenameRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder = db.query(Folder).filter(Folder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="目录不存在")

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
    return folder


@router.patch("/folders/{folder_id}/move", response_model=FolderItem)
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

    home_root = _get_home_root(db)

    # folder_id=NULL 在语义上表示“移动到 home”，不会生成新的 parent_id=NULL 根目录
    new_parent_id = data.parent_id
    if new_parent_id is None:
        new_parent_id = home_root.id

    if new_parent_id == folder_id:
        raise HTTPException(status_code=400, detail="不能移动到自己")

    new_parent = db.query(Folder).filter(Folder.id == new_parent_id).first()
    if not new_parent:
        raise HTTPException(status_code=404, detail="目标父目录不存在")

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
    return folder


@router.delete("/folders/{folder_id}")
def delete_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder = db.query(Folder).filter(Folder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="目录不存在")

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

    home_root = _get_home_root(db)

    if folder_id is None:
        folder_id = home_root.id
    else:
        folder = db.query(Folder).filter(Folder.id == folder_id).first()
        if not folder:
            raise HTTPException(status_code=400, detail="文件夹不存在")

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

    home_root = _get_home_root(db)

    # folder_id=NULL 在语义上等价于“移动到 home 根目录”
    new_folder_id = data.folder_id
    if new_folder_id is None:
        new_folder_id = home_root.id

    folder = db.query(Folder).filter(Folder.id == new_folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="目标目录不存在")

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

    folder_name = (
        db.query(Folder.name)
        .filter(Folder.id == file_record.folder_id)
        .scalar()
        if file_record.folder_id is not None
        else None
    )

    return {
        "id": file_record.id,
        "file_name": file_record.file_name,
        "file_type": file_record.file_type,
        "uploader": file_record.uploader,
        "upload_time": file_record.upload_time,
        "folder_id": file_record.folder_id,
        "folder_name": folder_name,
        "index_status": file_record.index_status,
        "mime_type": file_record.mime_type,
        "file_size": file_record.file_size,
    }


@router.delete("/{file_id}")
def delete_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_record = db.query(FileRecord).filter(FileRecord.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="文件不存在")

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
