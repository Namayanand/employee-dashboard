"""CSV -> database. The CSV stays the canonical source; this loads it into the
operational store. Idempotent by default (won't wipe edits on redeploy); pass
force=True to rebuild from scratch."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import func, select, text

from . import config
from .database import Base, engine, session_scope
from .models import FIELD_COLUMNS, INDEXED_COLUMNS, Employee


def create_schema() -> None:
    """Create the table (no indexes yet — those go on after the bulk load)."""
    Base.metadata.create_all(engine)


def current_count() -> int:
    with session_scope() as s:
        return s.scalar(select(func.count()).select_from(Employee)) or 0


def _create_indexes() -> None:
    """Build indexes AFTER data is loaded: inserting into an unindexed table is
    substantially faster, and one bulk index build beats N incremental updates."""
    with engine.begin() as conn:
        for col in INDEXED_COLUMNS:
            conn.execute(
                text(f"CREATE INDEX IF NOT EXISTS ix_employees_{col} "
                     f"ON employees ({col})")
            )


def ingest_csv(
    csv_path: str | Path | None = None,
    *,
    chunk_size: int | None = None,
    force: bool = False,
) -> int:
    """Load the master CSV in chunks. Returns the final row count."""
    csv_path = Path(csv_path or config.MASTER_CSV)
    if not csv_path.exists():
        raise FileNotFoundError(
            f"CSV not found at {csv_path}. Run scripts/generate_data.py first."
        )
    chunk_size = chunk_size or config.INGEST_CHUNK_SIZE

    create_schema()

    existing = current_count()
    if existing and not force:
        # Idempotent: data already present, don't clobber (important once the
        # DB lives on a persistent volume and holds user edits).
        return existing

    if force:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM employees"))

    total = 0
    for chunk in pd.read_csv(csv_path, chunksize=chunk_size):
        chunk = chunk[[c for c in FIELD_COLUMNS if c in chunk.columns]]
        if "date_of_joining" in chunk.columns:
            # Store as plain date (YYYY-MM-DD), not a full timestamp, so the
            # Date column round-trips cleanly.
            chunk["date_of_joining"] = pd.to_datetime(
                chunk["date_of_joining"]
            ).dt.date
        chunk.to_sql("employees", engine, if_exists="append", index=False)
        total += len(chunk)

    _create_indexes()
    return total
