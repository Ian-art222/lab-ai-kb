from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Lab AI KB API"
    app_env: str = "dev"
    database_url: str = "postgresql+psycopg://postgres:LabKb_2026_StrongPass!@db:5432/lab_ai_kb"
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24
    upload_dir: str = "uploads"

    # 浏览器访问前端的 Origin（逗号分隔），供 FastAPI CORS；与 Nginx 同域时多数请求不触发跨域校验
    cors_allowed_origins: str = (
        "http://10.65.218.208:8080,"
        "http://localhost:8080,http://127.0.0.1:8080,"
        "http://localhost:5173,http://127.0.0.1:5173"
    )

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
    qa_retrieval_mode: str = "hybrid"  # semantic | lexical | hybrid
    qa_semantic_threshold: float = 0.25
    qa_lexical_threshold: float = 0.012
    qa_hybrid_threshold: float = 0.012
    qa_pgvector_retrieval_enabled: bool = True
    qa_pgvector_probe_limit: int = 256
    qa_retrieval_log_top_n: int = 5

    # Rerank
    qa_rerank_enabled: bool = True
    qa_rerank_top_n: int = 20
    qa_rerank_model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    qa_rerank_latency_budget_ms: int = 1200

    # Query-side enhancement (lightweight and optional)
    qa_query_expansion_enabled: bool = False
    qa_query_expansion_max_queries: int = 3

    # Query 理解 / 重写（规则型，接入检索 embedding 与 lexical）
    qa_enable_query_rewrite: bool = True
    qa_max_sub_queries: int = 3
    qa_max_retrieval_queries: int = 8
    qa_enable_multi_query_for_compare: bool = True
    qa_enable_multi_query_expansion: bool = True
    qa_query_rewrite_trace_enabled: bool = False

    # 答案生成层：按意图组织输出、证据保守措辞、冲突提示
    qa_enable_answer_style_by_query_type: bool = True
    qa_enable_evidence_sufficiency_guard: bool = True
    qa_enable_conflict_notice: bool = True

    # 抽取层（PDF/DOCX 等）版本标记，供 diagnostics 展示
    ingest_extractor_version: str = "extract_v2_rules"

    # Source diversity control (relevance-first, not forced multi-source)
    qa_max_chunks_per_doc: int = 2
    qa_target_distinct_docs: int = 3
    qa_min_distinct_docs_for_multi_source: int = 2
    qa_single_doc_dominance_ratio: float = 1.6
    qa_diversity_rerank_enabled: bool = False
    qa_diversity_lambda: float = 0.75
    qa_diversity_fetch_k: int = 24
    qa_redundancy_sim_threshold: float = 0.9
    qa_redundancy_adjacent_window: int = 1

    # Grounding guardrail
    qa_strict_min_citations: int = 1
    qa_min_grounded_citations: int = 1

    # pgvector semantic search (dimension must match migration + DB column; mismatch → in-memory fallback)
    qa_pgvector_semantic_enabled: bool = True
    qa_pgvector_dimensions: int = 1536

    # Governance / diagnostics
    qa_failure_cases_dir: str = "evals/fixtures/failure_cases"

    # Chunking / parsing (text-only)
    ingest_chunk_size: int = 1000
    ingest_chunk_overlap: int = 150
    ingest_min_chunk_chars: int = 80
    ingest_max_index_text_chars: int = 200000
    ingest_pdf_min_chars_per_page: int = 20
    # v3 结构感知管道：目标为「近似 token」，内部按中英启发式换算为字符预算
    ingest_structural_chunking_enabled: bool = True
    ingest_child_target_tokens: int = 220
    ingest_child_min_tokens: int = 100
    ingest_child_max_tokens: int = 360
    ingest_child_overlap_tokens: int = 45
    ingest_parent_target_tokens: int = 720
    ingest_parent_min_tokens: int = 350
    ingest_parent_max_tokens: int = 1100
    # 问答：命中 parent 上下文后，可拼接同文件相邻 parent（各侧最多 N 段，总附加字符上限）
    qa_adjacent_parent_max_per_side: int = 1
    qa_adjacent_parent_max_chars: int = 1200
    # 仅当相邻 parent 与当前 parent 的 heading_path 一致（或均为空）时才拼接
    qa_adjacent_parent_same_heading_only: bool = True

    # 检索后：coverage-aware 选择与 packing（多文件覆盖、冗余/垄断惩罚、provenance）
    qa_enable_coverage_aware_packing: bool = True
    # 与 qa_max_parents_per_file（旧多样化）区分：coverage 阶段单文件 distinct parent 槽上限
    qa_coverage_max_parents_per_file: int = 3
    qa_max_context_chars_per_file: int = 6000
    qa_max_children_per_parent: int = 2
    qa_enable_heading_diversity_bonus: bool = True
    qa_enable_redundancy_penalty_coverage: bool = True
    qa_redundancy_jaccard_threshold_coverage: float = 0.72
    qa_enable_dominant_source_penalty: bool = True
    qa_max_dominant_file_ratio: float = 0.65
    qa_min_distinct_files_compare: int = 2
    qa_min_distinct_files_summary: int = 2
    qa_min_distinct_files_multi_hop: int = 2
    qa_min_distinct_files_troubleshooting: int = 2
    qa_enable_citation_provenance: bool = True
    qa_enable_coverage_diagnostics: bool = True
    qa_enable_coverage_shortfall_guard: bool = True
    qa_packing_trace_enabled: bool = False

    # 检索后：parent 级多样化 / 去冗余 / packing（相关性优先，抑制单文档与同段落霸榜）
    qa_enable_diversification: bool = True
    qa_enable_mmr_like_rerank: bool = True
    qa_mmr_lambda: float = 0.7
    qa_max_parents_per_file: int = 2
    qa_max_parents_total: int = 6
    qa_max_parents_per_heading: int = 2
    qa_parent_similarity_dedup_threshold: float = 0.8
    qa_same_heading_dedup: bool = True
    # 多文档时单文件上下文字符软上限比例（相对总 budget，0.55≈55%）
    qa_pack_per_file_budget_ratio: float = 0.55

    # 调试：在 retrieval_meta 中附带分层追踪（体积可能较大）
    qa_debug_retrieval_trace_enabled: bool = False
    qa_debug_store_intermediate_matches: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
