from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class SettingItem(BaseModel):
    system_name: str
    lab_name: str
    llm_provider: str
    llm_api_base: str
    llm_api_key_masked: str
    llm_api_key_configured: bool
    llm_model: str
    embedding_provider: str
    embedding_api_base: str
    embedding_api_key_masked: str
    embedding_api_key_configured: bool
    embedding_model: str
    embedding_batch_size: int | None = None
    embedding_effective_batch_size: int
    qa_enabled: bool
    sidebar_auto_collapse: bool
    theme_mode: str
    last_llm_test_success: bool | None = None
    last_llm_test_at: datetime | None = None
    last_llm_test_detail: str | None = None
    last_embedding_test_success: bool | None = None
    last_embedding_test_at: datetime | None = None
    last_embedding_test_detail: str | None = None
    updated_at: datetime


class SettingUpdate(BaseModel):
    system_name: str
    lab_name: str
    llm_provider: str
    llm_api_base: str
    llm_api_key: str | None = None
    llm_model: str
    embedding_provider: str
    embedding_api_base: str
    embedding_api_key: str | None = None
    embedding_model: str
    embedding_batch_size: int | None = None
    qa_enabled: bool
    sidebar_auto_collapse: bool
    theme_mode: Literal["warm"]


class SettingStatus(BaseModel):
    qa_enabled: bool
    llm_provider: str
    llm_model: str
    llm_configured: bool
    embedding_provider: str
    embedding_model: str
    embedding_configured: bool
    embedding_batch_size: int | None = None
    embedding_effective_batch_size: int
    current_chat_standard: str
    current_index_standard: str
    indexed_files_count: int = 0
    index_standard_mismatch: bool = False
    index_standard_mismatch_count: int = 0
    sidebar_auto_collapse: bool
    theme_mode: str
    last_llm_test_success: bool | None = None
    last_llm_test_at: datetime | None = None
    last_llm_test_detail: str | None = None
    last_embedding_test_success: bool | None = None
    last_embedding_test_at: datetime | None = None
    last_embedding_test_detail: str | None = None


class ConnectionTestResult(BaseModel):
    ok: bool
    service: str
    detail: str


class LlmConnectionTestRequest(BaseModel):
    provider: str = "openai_compatible"
    api_base: str
    api_key: str
    model: str


class EmbeddingConnectionTestRequest(BaseModel):
    provider: str = "openai_compatible"
    api_base: str
    api_key: str
    model: str
