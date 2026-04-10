from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

_sql_echo = settings.app_env.lower() in ("dev", "development", "local", "test")
engine = create_engine(settings.database_url, echo=_sql_echo)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()