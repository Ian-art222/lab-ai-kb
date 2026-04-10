"""启动时输出 QA 路由摘要（不记录密钥），并可选探测 embedding 输出维度。"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from app.core.config import settings as app_settings
from app.db.session import SessionLocal
from app.models.system_setting import SystemSetting
from app.services.model_service import embed_texts
from app.services.settings_service import is_embedding_configured, is_llm_configured

logger = logging.getLogger(__name__)
# Uvicorn 默认日志配置常不把 app.* 的 INFO 打到控制台；用 uvicorn.error 保证 compose / k8s 可见
_startup = logging.getLogger("uvicorn.error")


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc or url[:80]
    except Exception:
        return url[:80] if url else ""


def log_qa_model_routing_summary(*, probe_embedding_dim: bool = True) -> None:
    """在进程启动时打印 chat / embedding / pgvector 维度配置；可选一次真实 embedding 探测。"""
    db = SessionLocal()
    try:
        row = db.query(SystemSetting).filter(SystemSetting.id == 1).first()
        if not row:
            _startup.info("QA routing summary: system_settings row missing")
            return

        _startup.info(
            "QA chat: provider=%s model=%s api_host=%s key_configured=%s",
            (row.llm_provider or "").strip() or "<empty>",
            (row.llm_model or "").strip() or "<empty>",
            _host(row.llm_api_base or ""),
            bool((row.llm_api_key or "").strip()),
        )
        _startup.info(
            "QA embedding: provider=%s model=%s api_host=%s key_configured=%s",
            (row.embedding_provider or "").strip() or "<empty>",
            (row.embedding_model or "").strip() or "<empty>",
            _host(row.embedding_api_base or ""),
            bool((row.embedding_api_key or "").strip()),
        )
        _startup.info(
            "QA pgvector: configured_dimension=%s (must match DB embedding_vec + live embedding output)",
            app_settings.qa_pgvector_dimensions,
        )
        _startup.info(
            "QA rerank: enabled=%s model=%s latency_budget_ms=%s",
            app_settings.qa_rerank_enabled,
            (app_settings.qa_rerank_model_name or "").strip() or "<empty>",
            app_settings.qa_rerank_latency_budget_ms,
        )

        if (row.embedding_provider or "").strip().lower() == "openai" and "bigmodel.cn" in (
            row.embedding_api_base or ""
        ).lower():
            _startup.warning(
                "embedding_provider=%r 指向智谱 OpenAI 兼容网关时，建议改为 openai_compatible 或 zhipu，"
                "避免与 OpenAI 官方适配器语义混淆（当前请求仍可走兼容路径）",
                row.embedding_provider,
            )

        if not probe_embedding_dim or not is_embedding_configured(row):
            return

        try:
            vecs = embed_texts(
                provider=row.embedding_provider,
                api_base=row.embedding_api_base,
                api_key=row.embedding_api_key,
                model=row.embedding_model,
                inputs=["__dim_probe__"],
                embedding_batch_size_from_db=row.embedding_batch_size,
            )
            dim = len(vecs[0]) if vecs and vecs[0] else 0
            _startup.info("QA embedding probe: live_output_dimension=%s", dim)
            if dim and dim != app_settings.qa_pgvector_dimensions:
                _startup.error(
                    "QA embedding 维度不一致: live=%s qa_pgvector_dimensions=%s — 请调整迁移/配置或 "
                    "EMBEDDING_EXTRA_PARAMS_JSON（如 dimensions），并全量 reindex",
                    dim,
                    app_settings.qa_pgvector_dimensions,
                )
        except Exception as exc:
            msg = str(exc).strip()
            if len(msg) > 240:
                msg = msg[:240] + "…"
            _startup.warning("QA embedding probe failed (check keys/base URL): %s", msg)

        if is_llm_configured(row):
            _startup.info("QA chat: llm layer configured (no live probe on startup)")
    finally:
        db.close()
