from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Lab AI KB API"
    app_env: str = "dev"
    database_url: str = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/lab_ai_kb"
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24
    upload_dir: str = "uploads"

    # LLM / Embeddings
    llm_provider: str = "openai_compatible"
    llm_api_base: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_api_version: str = ""
    llm_timeout: float = 60.0
    llm_extra_headers_json: str = ""
    llm_organization: str = ""
    llm_project: str = ""
    llm_extra_params_json: str = ""

    embedding_provider: str = "openai_compatible"
    embedding_api_base: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_api_version: str = ""
    embedding_timeout: float = 60.0
    embedding_extra_headers_json: str = ""
    embedding_organization: str = ""
    embedding_project: str = ""
    embedding_extra_params_json: str = ""

    embed_batch_size: int = 100
    embed_retry_times: int = 2
    embed_retry_base_delay: float = 1.0
    embed_batch_delay: float = 0.25

    # QA retrieval defaults (read in qa_service; not wired to AskRequest yet)
    qa_candidate_k: int = 16
    qa_max_context_chars: int = 24000
    qa_neighbor_window: int = 1
    qa_dedupe_adjacent_chunks: bool = True

    # Rerank
    qa_rerank_enabled: bool = False
    qa_rerank_top_n: int = 20
    qa_rerank_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # pgvector semantic search (dimension must match migration + DB column; mismatch → in-memory fallback)
    qa_pgvector_semantic_enabled: bool = True
    qa_pgvector_dimensions: int = 1536

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()