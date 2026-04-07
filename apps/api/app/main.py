from app.api.files import router as files_router
from app.api.admin_diagnostics import router as admin_diag_router
from app.api.qa import router as qa_router
from app.api.settings import router as settings_router
from app.api.users import router as users_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.auth import router as auth_router

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(files_router)
app.include_router(qa_router)
app.include_router(admin_diag_router)
app.include_router(users_router)
app.include_router(settings_router)


@app.get("/")
def read_root():
    return {
        "message": f"{settings.app_name} is running",
        "env": settings.app_env,
    }


@app.get("/health")
def health_check():
    return {"status": "ok"}
