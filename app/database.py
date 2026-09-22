"""SQLite 数据库与会话。"""
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_connection, _):
    # SQLite 默认不强制外键，显式开启以配合 ondelete=CASCADE
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_db():
    """FastAPI 依赖：提供请求级会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def _ensure_columns():
    """对旧版本数据库补齐新增列（SQLite 不支持自动 ALTER，显式检查）。"""
    inspector = inspect(engine)
    additions = {
        "runs": [("rule_version_id", "INTEGER REFERENCES rule_versions(id) ON DELETE SET NULL")],
        "steps": [
            ("safety_measures", "TEXT NOT NULL DEFAULT '[]'"),
            ("safety_note", "TEXT"),
            ("safety_confirmed", "BOOLEAN NOT NULL DEFAULT 0"),
            ("safety_confirmed_at", "DATETIME"),
            ("safety_confirmed_fp", "VARCHAR(64)"),
            ("safety_stale", "BOOLEAN NOT NULL DEFAULT 0"),
        ],
    }
    with engine.begin() as conn:
        for table, cols in additions.items():
            if table not in inspector.get_table_names():
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in cols:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
