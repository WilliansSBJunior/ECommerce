import os
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .config import DATABASE_URL
from .models import Base

engine = None
SessionLocal = None


def configure(url: str = DATABASE_URL) -> None:
    """(Re)cria a conexao. A CLI chama com --db para usar outro banco (ex: demo)."""
    global engine, SessionLocal
    if url.startswith("sqlite:///"):
        db_path = url.replace("sqlite:///", "", 1)
        if db_path and db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    engine = create_engine(url)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


configure()


def _ensure_columns() -> None:
    """Migracao leve: adiciona colunas novas em tabelas ja existentes.

    `create_all` so cria tabelas que faltam; se o banco foi criado por uma
    versao anterior do projeto, as colunas novas (marketplace, sold_30d, ...)
    precisam ser adicionadas com ALTER TABLE. Funciona em SQLite e Postgres.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                default = ""
                if column.default is not None and not callable(column.default.arg):
                    arg = column.default.arg
                    default = f" DEFAULT {arg!r}" if isinstance(arg, str) else f" DEFAULT {arg}"
                conn.execute(
                    text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {col_type}{default}')
                )


def init_db() -> None:
    Base.metadata.create_all(engine)
    _ensure_columns()


@contextmanager
def get_session() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
