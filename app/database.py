import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:@localhost/parkoptima")

if not DATABASE_URL:
    default_db_path = Path(__file__).resolve().parent.parent / "parkoptima.db"
    DATABASE_URL = f"sqlite:///{default_db_path}"

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

try:
    engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
    if DATABASE_URL.startswith("mysql"):
        with engine.connect():
            pass
except Exception:
    if DATABASE_URL.startswith("mysql"):
        default_db_path = Path(__file__).resolve().parent.parent / "parkoptima.db"
        fallback_url = f"sqlite:///{default_db_path}"
        engine = create_engine(fallback_url, connect_args={"check_same_thread": False}, pool_pre_ping=True)
    else:
        raise

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
