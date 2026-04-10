from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.file_record import FileRecord
from app.models.system_setting import SystemSetting
from app.schemas.setting import SettingItem, SettingStatus

MAX_EMBEDDING_BATCH_GLOBAL = 100
QWEN_FAMILY_MAX_EMBED_BATCH = 10
ZHIPU_FAMILY_MAX_EMBED_BATCH = 64


@dataclass(slots=True)
class IndexStandardSummary:
    current_chat_standard: str
    current_index_standard: str
    indexed_files_count: int
    mismatch_count: int


def embedding_provider_is_qwen_family(raw: str) -> bool:
    key = (raw or "").strip().lower()
    return key in ("qwen", "dashscope")


def embedding_provider_is_zhipu_family(raw: str) -> bool:
    key = (raw or "").strip().lower()
    return key in ("zhipu", "bigmodel", "glm")


def canonical_embedding_provider(raw: str | None) -> str:
    key = (raw or "").strip().lower()
    if embedding_provider_is_qwen_family(key):
        return "qwen"
    if embedding_provider_is_zhipu_family(key):
        return "zhipu"
    return key


def build_chat_standard(*, llm_provider: str | None, llm_model: str | None) -> str:
    provider = (llm_provider or "").strip().lower()
    model = (llm_model or "").strip()
    if not provider or not model:
        return ""
    return f"{provider}:{model}"


def build_embedding_index_standard(
    *,
    embedding_provider: str | None,
    embedding_model: str | None,
) -> str:
    provider = canonical_embedding_provider(embedding_provider)
    model = (embedding_model or "").strip()
    if not provider or not model:
        return ""
    return f"{provider}:{model}"


def get_effective_embedding_batch_size(
    *,
    embedding_provider_raw: str,
    db_batch_size: int | None,
) -> int:
    from app.core.config import settings as app_settings

    if db_batch_size is not None:
        base = max(1, min(db_batch_size, MAX_EMBEDDING_BATCH_GLOBAL))
    else:
        base = max(1, min(app_settings.embed_batch_size, MAX_EMBEDDING_BATCH_GLOBAL))

    if embedding_provider_is_qwen_family(embedding_provider_raw):
        base = min(base, QWEN_FAMILY_MAX_EMBED_BATCH)

    if embedding_provider_is_zhipu_family(embedding_provider_raw):
        base = min(base, ZHIPU_FAMILY_MAX_EMBED_BATCH)

    return max(1, base)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}{'*' * (len(value) - 6)}{value[-3:]}"


def get_or_create_settings(db: Session) -> SystemSetting:
    settings = db.query(SystemSetting).filter(SystemSetting.id == 1).first()
    if settings:
        return settings

    settings = SystemSetting(id=1, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def is_llm_configured(settings: SystemSetting) -> bool:
    return bool(settings.llm_provider and settings.llm_api_base and settings.llm_api_key and settings.llm_model)


def is_embedding_configured(settings: SystemSetting) -> bool:
    return bool(
        settings.embedding_provider
        and settings.embedding_api_base
        and settings.embedding_api_key
        and settings.embedding_model
    )


def get_index_standard_summary(db: Session, settings: SystemSetting) -> IndexStandardSummary:
    current_index_standard = build_embedding_index_standard(
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
    )
    current_chat_standard = build_chat_standard(
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
    )
    indexed_files = db.query(FileRecord).filter(FileRecord.index_status == "indexed").all()
    mismatch_count = 0
    if current_index_standard:
        for file_record in indexed_files:
            file_standard = build_embedding_index_standard(
                embedding_provider=file_record.index_embedding_provider,
                embedding_model=file_record.index_embedding_model,
            )
            if not file_standard or file_standard != current_index_standard:
                mismatch_count += 1
    return IndexStandardSummary(
        current_chat_standard=current_chat_standard,
        current_index_standard=current_index_standard,
        indexed_files_count=len(indexed_files),
        mismatch_count=mismatch_count,
    )


def to_setting_item(settings: SystemSetting) -> SettingItem:
    return SettingItem(
        system_name=settings.system_name,
        lab_name=settings.lab_name,
        llm_provider=settings.llm_provider,
        llm_api_base=settings.llm_api_base,
        llm_api_key_masked=mask_secret(settings.llm_api_key),
        llm_api_key_configured=bool(settings.llm_api_key),
        llm_model=settings.llm_model,
        embedding_provider=settings.embedding_provider,
        embedding_api_base=settings.embedding_api_base,
        embedding_api_key_masked=mask_secret(settings.embedding_api_key),
        embedding_api_key_configured=bool(settings.embedding_api_key),
        embedding_model=settings.embedding_model,
        embedding_batch_size=settings.embedding_batch_size,
        embedding_effective_batch_size=get_effective_embedding_batch_size(
            embedding_provider_raw=settings.embedding_provider,
            db_batch_size=settings.embedding_batch_size,
        ),
        qa_enabled=settings.qa_enabled,
        sidebar_auto_collapse=settings.sidebar_auto_collapse,
        theme_mode=settings.theme_mode,
        last_llm_test_success=settings.last_llm_test_success,
        last_llm_test_at=settings.last_llm_test_at,
        last_llm_test_detail=settings.last_llm_test_detail,
        last_embedding_test_success=settings.last_embedding_test_success,
        last_embedding_test_at=settings.last_embedding_test_at,
        last_embedding_test_detail=settings.last_embedding_test_detail,
        updated_at=settings.updated_at,
    )


def to_setting_status(settings: SystemSetting) -> SettingStatus:
    summary = IndexStandardSummary(
        current_chat_standard=build_chat_standard(
            llm_provider=settings.llm_provider,
            llm_model=settings.llm_model,
        ),
        current_index_standard=build_embedding_index_standard(
            embedding_provider=settings.embedding_provider,
            embedding_model=settings.embedding_model,
        ),
        indexed_files_count=0,
        mismatch_count=0,
    )
    return SettingStatus(
        qa_enabled=settings.qa_enabled,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        llm_configured=is_llm_configured(settings),
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
        embedding_configured=is_embedding_configured(settings),
        embedding_batch_size=settings.embedding_batch_size,
        embedding_effective_batch_size=get_effective_embedding_batch_size(
            embedding_provider_raw=settings.embedding_provider,
            db_batch_size=settings.embedding_batch_size,
        ),
        current_chat_standard=summary.current_chat_standard,
        current_index_standard=summary.current_index_standard,
        indexed_files_count=summary.indexed_files_count,
        index_standard_mismatch=summary.mismatch_count > 0,
        index_standard_mismatch_count=summary.mismatch_count,
        sidebar_auto_collapse=settings.sidebar_auto_collapse,
        theme_mode=settings.theme_mode,
        last_llm_test_success=settings.last_llm_test_success,
        last_llm_test_at=settings.last_llm_test_at,
        last_llm_test_detail=settings.last_llm_test_detail,
        last_embedding_test_success=settings.last_embedding_test_success,
        last_embedding_test_at=settings.last_embedding_test_at,
        last_embedding_test_detail=settings.last_embedding_test_detail,
    )


def to_setting_status_with_index_summary(
    settings: SystemSetting,
    *,
    summary: IndexStandardSummary,
) -> SettingStatus:
    status = to_setting_status(settings)
    status.current_chat_standard = summary.current_chat_standard
    status.current_index_standard = summary.current_index_standard
    status.indexed_files_count = summary.indexed_files_count
    status.index_standard_mismatch = summary.mismatch_count > 0
    status.index_standard_mismatch_count = summary.mismatch_count
    return status


def mark_last_qa_status(
    db: Session,
    *,
    success: bool,
    error_message: str | None,
) -> None:
    settings = get_or_create_settings(db)
    settings.last_qa_success = success
    settings.last_qa_at = datetime.utcnow()
    settings.last_qa_error = error_message if not success else None
    db.commit()


def record_model_test_result(
    db: Session,
    *,
    service: str,
    success: bool,
    detail: str,
) -> SystemSetting:
    settings = get_or_create_settings(db)
    now = datetime.utcnow()
    if service == "llm":
        settings.last_llm_test_success = success
        settings.last_llm_test_at = now
        settings.last_llm_test_detail = detail
    elif service == "embedding":
        settings.last_embedding_test_success = success
        settings.last_embedding_test_at = now
        settings.last_embedding_test_detail = detail
    settings.updated_at = now
    db.commit()
    db.refresh(settings)
    return settings
