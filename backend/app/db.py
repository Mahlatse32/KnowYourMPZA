from collections.abc import Generator

from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings
from app.db_engine import create_app_engine


class Base(DeclarativeBase):
    pass


# create_app_engine keeps pool_pre_ping=True and disables psycopg prepared
# statements for postgresql+psycopg URLs (PgBouncer/Supabase pooler safe).
engine = create_app_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
