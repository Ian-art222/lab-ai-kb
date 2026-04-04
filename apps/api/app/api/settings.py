from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.setting import (
    ConnectionTestResult,
    EmbeddingConnectionTestRequest,
    LlmConnectionTestRequest,
    SettingItem,
    SettingStatus,
    SettingUpdate,
)
from app.services.model_service import chat_completion, embed_texts
from app.services.settings_service import (
    MAX_EMBEDDING_BATCH_GLOBAL,
    embedding_provider_is_qwen_family,
    get_index_standard_summary,
    get_or_create_settings,
    mask_secret,
    record_model_test_result,
    to_setting_item,
    to_setting_status,
    to_setting_status_with_index_summary,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _resolve_secret_update(raw_value: str | None, current_value: str) -> str | None:
    if raw_value is None:
        return None
    next_value = raw_value.strip()
    if not next_value:
        return None
    if next_value == mask_secret(current_value):
        return None
    return next_value


def _validate_provider_selection(*, llm_provider: str, embedding_provider: str) -> None:
    if embedding_provider.strip() == "anthropic":
        raise HTTPException(
            status_code=400,
            detail="Anthropic 当前仅支持 chat，不支持 embeddings，请改用 Gemini、OpenAI 或 OpenAI-compatible provider",
        )


def _validate_embedding_batch_size(*, embedding_provider: str, value: int | None) -> None:
    if value is None:
        return
    if value < 1 or value > MAX_EMBEDDING_BATCH_GLOBAL:
        raise HTTPException(
            status_code=400,
            detail=(
                f"embedding_batch_size 必须为 1–{MAX_EMBEDDING_BATCH_GLOBAL} 的整数；"
                "留空则按环境变量 EMBED_BATCH_SIZE 与代码默认值生效"
            ),
        )
    if embedding_provider_is_qwen_family(embedding_provider) and value > 10:
        raise HTTPException(
            status_code=400,
            detail=(
                "Qwen / DashScope（如 text-embedding-v4）单批最多 10 条，"
                "请将 Embedding Batch Size 设为不超过 10"
            ),
        )


@router.get("", response_model=SettingItem)
def get_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = get_or_create_settings(db)
    return to_setting_item(settings)


@router.put("", response_model=SettingItem)
def update_settings(
    data: SettingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _validate_provider_selection(
        llm_provider=data.llm_provider,
        embedding_provider=data.embedding_provider,
    )
    _validate_embedding_batch_size(
        embedding_provider=data.embedding_provider,
        value=data.embedding_batch_size,
    )
    settings = get_or_create_settings(db)
    settings.system_name = data.system_name
    settings.lab_name = data.lab_name
    settings.llm_provider = data.llm_provider
    settings.llm_api_base = data.llm_api_base
    settings.llm_model = data.llm_model
    settings.embedding_provider = data.embedding_provider
    settings.embedding_api_base = data.embedding_api_base
    settings.embedding_model = data.embedding_model
    settings.embedding_batch_size = data.embedding_batch_size
    settings.qa_enabled = data.qa_enabled
    settings.sidebar_auto_collapse = data.sidebar_auto_collapse
    settings.theme_mode = data.theme_mode
    settings.updated_at = datetime.utcnow()

    next_llm_key = _resolve_secret_update(data.llm_api_key, settings.llm_api_key)
    next_embedding_key = _resolve_secret_update(
        data.embedding_api_key, settings.embedding_api_key
    )
    if next_llm_key is not None:
        settings.llm_api_key = next_llm_key
    if next_embedding_key is not None:
        settings.embedding_api_key = next_embedding_key

    db.commit()
    db.refresh(settings)
    return to_setting_item(settings)


@router.get("/status", response_model=SettingStatus)
def get_settings_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = get_or_create_settings(db)
    summary = get_index_standard_summary(db, settings)
    return to_setting_status_with_index_summary(settings, summary=summary)


@router.post("/test/embedding", response_model=ConnectionTestResult)
def test_embedding_connection(
    data: EmbeddingConnectionTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    settings = get_or_create_settings(db)
    provider = data.provider.strip() or settings.embedding_provider
    _validate_provider_selection(
        llm_provider=settings.llm_provider,
        embedding_provider=provider,
    )
    api_base = data.api_base.strip()
    api_key = data.api_key.strip() or settings.embedding_api_key
    model = data.model.strip()
    if not (provider and api_base and api_key and model):
        raise HTTPException(status_code=400, detail="Embedding 配置不完整")

    try:
        vectors = embed_texts(
            provider=provider,
            api_base=api_base,
            api_key=api_key,
            model=model,
            inputs=["ping"],
            embedding_batch_size_from_db=settings.embedding_batch_size,
        )
        if not vectors or not vectors[0]:
            raise RuntimeError("Embedding 服务未返回有效向量")
        record_model_test_result(
            db,
            service="embedding",
            success=True,
            detail="Embedding 连接测试成功",
        )
        return ConnectionTestResult(
            ok=True,
            service="embedding",
            detail="Embedding 连接测试成功",
        )
    except RuntimeError as exc:
        record_model_test_result(
            db,
            service="embedding",
            success=False,
            detail=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/test/llm", response_model=ConnectionTestResult)
def test_llm_connection(
    data: LlmConnectionTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    settings = get_or_create_settings(db)
    provider = data.provider.strip() or settings.llm_provider
    api_base = data.api_base.strip()
    api_key = data.api_key.strip() or settings.llm_api_key
    model = data.model.strip()
    if not (provider and api_base and api_key and model):
        raise HTTPException(status_code=400, detail="LLM 配置不完整")

    try:
        content = chat_completion(
            provider=provider,
            api_base=api_base,
            api_key=api_key,
            model=model,
            messages=[{"role": "user", "content": "请仅回复：pong"}],
        )
        detail = f"LLM 连接测试成功：{content[:80]}"
        record_model_test_result(
            db,
            service="llm",
            success=True,
            detail=detail,
        )
        return ConnectionTestResult(
            ok=True,
            service="llm",
            detail=detail,
        )
    except RuntimeError as exc:
        record_model_test_result(
            db,
            service="llm",
            success=False,
            detail=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
