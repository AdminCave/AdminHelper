from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import DATABASE_URL

# Postgres-Pool: ThreadPoolExecutor (Hooks, 4 Worker) + APScheduler +
# uvicorn + Web-Requests = realistisch 15-20 Connections peak.
# pool_pre_ping=True faengt tot-Connections nach Container-Restarts.
engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
