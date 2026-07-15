"""Engine + session plumbing. The whole point of routing through SQLAlchemy is
that switching SQLite (dev) -> Turso / Postgres (prod) is a single URL change in
config; no query or model code changes."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _make_engine(url: str):
    connect_args = {}
    if url.startswith("sqlite"):
        # Streamlit reruns across threads; this keeps SQLite happy.
        connect_args["check_same_thread"] = False

    engine = create_engine(url, echo=False, future=True, connect_args=connect_args)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL;")   # better concurrent reads
            cur.execute("PRAGMA foreign_keys=ON;")
            cur.close()

    return engine


engine = _make_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False, future=True
)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session: commits on success, rolls back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
