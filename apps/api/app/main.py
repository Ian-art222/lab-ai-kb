from app.api.files import router as files_router
from app.api.qa import router as qa_router
from app.api.settings import router as settings_router
from app.api.users import router as users_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.auth import router as auth_router
from app.api.admin_diagnostics import router as admin_diagnostics_router


def _parse_cors_origins() -> list[str]:
    raw = (settings.cors_allowed_origins or "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


app = FastAPI(title=settings.app_name)

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


@app.get("/")
def read_root():
    return {
        "message": f"{settings.app_name} is running",
        "env": settings.app_env,
    }


@app.get("/health")
def health_check():
    return {"status": "ok"}