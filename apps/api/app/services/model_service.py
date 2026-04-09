from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.core.config import settings
from app.services.settings_service import get_effective_embedding_batch_size
from app.services.provider_adapters import (
    ChatMessage,
    ChatRequest,
    EmbedRequest,
    ProviderConfig,
    ProviderRequestError,
    get_provider_adapter,
    normalize_provider_name,
)

logger = logging.getLogger(__name__)
# Env-only default when callers do not pass DB override (see get_effective_embedding_batch_size).
MAX_EMBED_REQUESTS_PER_BATCH = max(1, min(settings.embed_batch_size, 100))
EMBED_RETRY_TIMES = max(0, settings.embed_retry_times)
EMBED_RETRY_BASE_DELAY = max(0.1, settings.embed_retry_base_delay)
EMBED_BATCH_DELAY = max(0.0, settings.embed_batch_delay)


def _load_json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _build_provider_config(
    *,
    provider: str | None,
    api_base: str,
    api_key: str,
    model: str,
    api_version: str | None,
    timeout: float | None,
    extra_headers: dict[str, str] | None,
    organization: str | None,
    project: str | None,
    extra_params: dict[str, Any] | None,
) -> ProviderConfig:
    return ProviderConfig(
        provider=normalize_provider_name(provider),
        api_base=api_base,
        api_key=api_key,
        model=model,
        api_version=api_version,
        timeout=timeout or 60.0,
        extra_headers=extra_headers or {},
        organization=organization,
        project=project,
        extra_params=extra_params or {},
    )


def _normalize_provider_error(exc: ProviderRequestError) -> str:
    if exc.code == "RATE_LIMIT":
        return f"当前触发 {exc.provider} 限流或配额限制，建议稍后重试。原始错误：{exc.detail}"
    if exc.code == "AUTH_ERROR":
        return f"{exc.provider} 认证失败，请检查 API Key、组织/项目配置或权限范围。原始错误：{exc.detail}"
    if exc.code == "NOT_FOUND":
        return f"{exc.provider} 请求的模型或接口路径不存在，请检查 provider、base URL 与 model 配置。原始错误：{exc.detail}"
    if exc.code == "BAD_REQUEST":
        return f"{exc.provider} 请求参数不合法，请检查当前 provider 与模型参数配置。原始错误：{exc.detail}"
    if exc.code == "READ_TIMEOUT":
        return (
            f"{exc.provider} 读取模型响应超时（上游在配置的超时时间内未传完数据）。"
            f"可增大环境变量中的 llm_timeout 或 pdf_translation_llm_timeout（全文翻译）。原始：{exc.detail}"
        )
    if exc.code == "NETWORK_ERROR":
        return f"{exc.provider} 网络连接失败，请检查服务地址、代理或外网访问状态。原始错误：{exc.detail}"
    if exc.code == "PROVIDER_ERROR":
        return f"{exc.provider} 服务暂时不可用，请稍后重试。原始错误：{exc.detail}"
    return exc.detail


def _normalize_chat_messages(messages: list[dict[str, str]]) -> tuple[str | None, list[ChatMessage]]:
    system_parts: list[str] = []
    normalized_messages: list[ChatMessage] = []
    for message in messages:
        role = message.get("role", "").strip()
        content = message.get("content", "").strip()
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
            continue
        normalized_messages.append(ChatMessage(role=role or "user", content=content))
    system_prompt = "\n".join(system_parts).strip() or None
    return system_prompt, normalized_messages


def _request_embed_batch(
    *,
    config: ProviderConfig,
    batch_inputs: list[str],
    batch_index: int,
    total_batches: int,
) -> list[list[float]]:
    adapter = get_provider_adapter(config.provider)
    last_error: ProviderRequestError | None = None

    for attempt in range(EMBED_RETRY_TIMES + 1):
        try:
            response = adapter.embed_texts(
                config,
                EmbedRequest(provider=config.provider, model=config.model, inputs=batch_inputs),
            )
            return response.embeddings
        except ProviderRequestError as exc:
            last_error = exc
            retries_used = attempt
            if not exc.retryable or attempt >= EMBED_RETRY_TIMES:
                raise RuntimeError(
                    f"Embedding 第 {batch_index}/{total_batches} 批请求失败（provider={config.provider}，batch_size={len(batch_inputs)}，已重试 {retries_used} 次）: "
                    f"{_normalize_provider_error(exc)}"
                ) from exc
            delay = EMBED_RETRY_BASE_DELAY * (2**attempt)
            logger.warning(
                "Embedding batch retry scheduled: provider=%s batch=%s/%s attempt=%s/%s delay=%.2fs code=%s detail=%s",
                config.provider,
                batch_index,
                total_batches,
                attempt + 1,
                EMBED_RETRY_TIMES,
                delay,
                exc.code,
                exc.detail,
            )
            time.sleep(delay)

    if last_error is None:
        raise RuntimeError(
            f"Embedding 第 {batch_index}/{total_batches} 批请求失败（provider={config.provider}，batch_size={len(batch_inputs)}）: 未知错误"
        )
    raise RuntimeError(
        f"Embedding 第 {batch_index}/{total_batches} 批请求失败（provider={config.provider}，batch_size={len(batch_inputs)}，已重试 {EMBED_RETRY_TIMES} 次）: "
        f"{_normalize_provider_error(last_error)}"
    )


def embed_texts(
    *,
    api_base: str,
    api_key: str,
    model: str,
    inputs: list[str],
    provider: str | None = None,
    api_version: str | None = None,
    timeout: float | None = None,
    extra_headers: dict[str, str] | None = None,
    organization: str | None = None,
    project: str | None = None,
    extra_params: dict[str, Any] | None = None,
    embedding_batch_size_from_db: int | None = None,
) -> list[list[float]]:
    provider_raw = provider or settings.embedding_provider
    provider_name = normalize_provider_name(provider_raw)
    if not api_base or not api_key or not model:
        raise RuntimeError("Embedding 配置不完整")
    if not inputs:
        return []

    config = _build_provider_config(
        provider=provider_name,
        api_base=api_base,
        api_key=api_key,
        model=model,
        api_version=api_version or settings.embedding_api_version,
        timeout=timeout or settings.embedding_timeout,
        extra_headers=extra_headers or _load_json_dict(settings.embedding_extra_headers_json),
        organization=organization or settings.embedding_organization or None,
        project=project or settings.embedding_project or None,
        extra_params=extra_params or _load_json_dict(settings.embedding_extra_params_json),
    )
    adapter = get_provider_adapter(config.provider)
    if not adapter.capabilities.supports_embeddings:
        raise RuntimeError(f"{config.provider} 当前不支持 embeddings")

    effective_batch = get_effective_embedding_batch_size(
        embedding_provider_raw=provider_raw,
        db_batch_size=embedding_batch_size_from_db,
    )
    logger.info(
        "Embedding batching: effective_batch_size=%s provider_raw=%s provider_normalized=%s "
        "db_batch_size=%s env_embed_batch_size=%s",
        effective_batch,
        (provider_raw or "").strip(),
        config.provider,
        embedding_batch_size_from_db,
        settings.embed_batch_size,
    )

    embeddings: list[list[float]] = []
    total_batches = (len(inputs) + effective_batch - 1) // effective_batch

    for batch_index, start in enumerate(range(0, len(inputs), effective_batch), start=1):
        batch_inputs = inputs[start : start + effective_batch]
        logger.info(
            "Embedding batch request started: provider=%s effective_batch_size=%s batch=%s/%s size=%s",
            config.provider,
            effective_batch,
            batch_index,
            total_batches,
            len(batch_inputs),
        )
        batch_embeddings = _request_embed_batch(
            config=config,
            batch_inputs=batch_inputs,
            batch_index=batch_index,
            total_batches=total_batches,
        )
        if len(batch_embeddings) != len(batch_inputs):
            raise RuntimeError(
                f"Embedding 第 {batch_index}/{total_batches} 批返回数量异常，期待 {len(batch_inputs)} 条，实际 {len(batch_embeddings)} 条"
            )
        for item_offset, embedding in enumerate(batch_embeddings, start=1):
            if not isinstance(embedding, list) or not embedding:
                raise RuntimeError(
                    f"Embedding 第 {batch_index}/{total_batches} 批第 {item_offset} 条结果缺少有效 embedding"
                )
        embeddings.extend(batch_embeddings)
        logger.info(
            "Embedding batch request finished: provider=%s batch=%s/%s collected=%s",
            config.provider,
            batch_index,
            total_batches,
            len(embeddings),
        )
        if EMBED_BATCH_DELAY > 0 and batch_index < total_batches:
            time.sleep(EMBED_BATCH_DELAY)

    if len(embeddings) != len(inputs):
        raise RuntimeError(
            f"Embedding 总返回数量异常，期待 {len(inputs)} 条，实际 {len(embeddings)} 条"
        )
    return embeddings


def chat_completion(
    *,
    api_base: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    provider: str | None = None,
    api_version: str | None = None,
    timeout: float | None = None,
    extra_headers: dict[str, str] | None = None,
    organization: str | None = None,
    project: str | None = None,
    extra_params: dict[str, Any] | None = None,
) -> str:
    provider_name = normalize_provider_name(provider or settings.llm_provider)
    if not api_base or not api_key or not model:
        raise RuntimeError("LLM 配置不完整")

    config = _build_provider_config(
        provider=provider_name,
        api_base=api_base,
        api_key=api_key,
        model=model,
        api_version=api_version or settings.llm_api_version,
        timeout=timeout or settings.llm_timeout,
        extra_headers=extra_headers or _load_json_dict(settings.llm_extra_headers_json),
        organization=organization or settings.llm_organization or None,
        project=project or settings.llm_project or None,
        extra_params=extra_params or _load_json_dict(settings.llm_extra_params_json),
    )
    adapter = get_provider_adapter(config.provider)
    if not adapter.capabilities.supports_chat:
        raise RuntimeError(f"{config.provider} 当前不支持 chat")

    system_prompt, normalized_messages = _normalize_chat_messages(messages)
    try:
        response = adapter.generate(
            config,
            ChatRequest(
                provider=config.provider,
                model=config.model,
                messages=normalized_messages,
                system_prompt=system_prompt,
            ),
        )
        return response.text
    except ProviderRequestError as exc:
        raise RuntimeError(_normalize_provider_error(exc)) from exc
