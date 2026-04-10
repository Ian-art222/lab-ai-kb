from app.api.files import router as files_router
from app.api.qa import router as qa_router
from app.api.settings import router as settings_router
from app.api.users import router as users_router
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.auth import router as auth_router
from app.api.admin_diagnostics import router as admin_diagnostics_router
from app.api.pdf_documents import router as pdf_documents_router


def _parse_cors_origins() -> list[str]:
    raw = (settings.cors_allowed_origins or "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    import logging

    slog = logging.getLogger("lab_ai_kb.startup")
    try:
        from app.core.startup_diagnostics import log_qa_model_routing_summary

        log_qa_model_routing_summary()
    except Exception as exc:
        slog.warning("startup diagnostics skipped: %s", exc)

    stale_stop = threading.Event()

    def _stale_reclaim_loop() -> None:
        from app.core.config import settings as _settings
        from app.services.index_stale_reclaim_service import run_stale_reclaim_once

        interval = max(60, int(_settings.index_stale_scan_interval_seconds))
        while not stale_stop.wait(interval):
            try:
                run_stale_reclaim_once()
            except Exception as exc:
                slog.warning("index stale reclaim periodic scan failed: %s", exc)

    try:
        from app.services.index_stale_reclaim_service import run_stale_reclaim_once

        n = run_stale_reclaim_once()
        if n:
            slog.info("index stale reclaim on startup reclaimed=%s", n)
    except Exception as exc:
        slog.warning("index stale reclaim on startup skipped: %s", exc)

    stale_thread = threading.Thread(
        target=_stale_reclaim_loop,
        name="index-stale-reclaim",
        daemon=True,
    )
    stale_thread.start()

    try:
        yield
    finally:
        stale_stop.set()


app = FastAPI(title=settings.app_name, lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(files_router)
app.include_router(qa_router)
app.include_router(users_router)
app.include_router(settings_router)
app.include_router(admin_diagnostics_router)
app.include_router(pdf_documents_router)


@app.get("/")
def read_root():
    return {
        "message": f"{settings.app_name} is running",
        "env": settings.app_env,
    }


@app.get("/health")
def health_check():
    return {"status": "ok"}
