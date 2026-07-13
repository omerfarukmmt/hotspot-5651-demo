"""PostgreSQL bağlantı katmanı (SQLAlchemy)."""
import os
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://hotspot:hotspot_secret@postgres:5432/hotspot_db",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def wait_for_db(max_attempts: int = 30, delay_seconds: float = 2.0) -> None:
    """Container açılış sırasına karşı dayanıklılık: Postgres hazır olana kadar bekle."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print(f"[database] PostgreSQL hazır (deneme {attempt}).", flush=True)
            return
        except OperationalError as exc:
            last_error = exc
            print(f"[database] PostgreSQL bekleniyor... ({attempt}/{max_attempts})", flush=True)
            time.sleep(delay_seconds)
    raise RuntimeError(f"PostgreSQL'e bağlanılamadı: {last_error}")


def get_db():
    """FastAPI dependency: istek başına DB oturumu."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
