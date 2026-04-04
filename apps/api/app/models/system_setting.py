from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    system_name: Mapped[str] = mapped_column(String(100), default="实验室知识库", nullable=False)
    lab_name: Mapped[str] = mapped_column(String(100), default="实验室内部", nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(50), default="openai_compatible", nullable=False)
    llm_api_base: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    llm_api_key: Mapped[str] = mapped_column(Text, default="", nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    embedding_provider: Mapped[str] = mapped_column(
        String(50), default="openai_compatible", nullable=False
    )
    embedding_api_base: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    embedding_api_key: Mapped[str] = mapped_column(Text, default="", nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    embedding_batch_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sidebar_auto_collapse: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    theme_mode: Mapped[str] = mapped_column(String(20), default="warm", nullable=False)
    last_qa_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_qa_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_qa_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_llm_test_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_llm_test_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_llm_test_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_embedding_test_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_embedding_test_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_embedding_test_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
