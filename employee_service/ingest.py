"""CSV -> database. The CSV stays the canonical source; this loads it into the
operational store. Idempotent by default (won't wipe edits on redeploy); pass
force=True to rebuild from scratch."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import func, select, text, update

from . import config
from .database import Base, engine, session_scope
from .exceptions import SchemaMismatch
from .models import FIELD_COLUMNS, INDEXED_COLUMNS, Employee

# Every business column is NOT NULL, so all of them are required in an upload.
REQUIRED_COLUMNS = FIELD_COLUMNS


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


# --------------------------------------------------------------------------- #
# Bulk upload: append arbitrary CSVs that conform to the schema
# --------------------------------------------------------------------------- #
def _existing_keys() -> tuple[set, set]:
    """The emp_ids and emails already stored, to skip duplicate inserts."""
    with session_scope() as s:
        ids = set(s.scalars(select(Employee.emp_id)).all())
        emails = set(s.scalars(select(Employee.email)).all())
    return ids, emails


def _coerce_to_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only the schema columns (in order) and coerce types. Raises
    SchemaMismatch if any required column is absent. Bad values become NaN/NaT
    here and are dropped by the caller."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaMismatch(
            "CSV does not conform to the employee schema. Missing column(s): "
            + ", ".join(missing)
        )
    df = df[REQUIRED_COLUMNS].copy()  # drop any extra columns, fix ordering
    df["date_of_joining"] = pd.to_datetime(df["date_of_joining"], errors="coerce")
    for col in ("age", "salary", "performance_rating"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _native(value):
    """psycopg2 can't adapt numpy scalars; unwrap them to native Python types
    (dates and strings pass through untouched)."""
    return value.item() if hasattr(value, "item") else value


def _bulk_insert(df: pd.DataFrame, chunk_size: int) -> int:
    added = 0
    for start in range(0, len(df), chunk_size):
        part = df.iloc[start:start + chunk_size]
        part.to_sql("employees", engine, if_exists="append", index=False)
        added += len(part)
    return added


def _bulk_update(df: pd.DataFrame) -> int:
    """Overwrite existing rows (matched by emp_id) with the uploaded values.
    emp_id itself is the match key and never changes."""
    if df.empty:
        return 0
    fields = [c for c in REQUIRED_COLUMNS if c != "emp_id"]
    with session_scope() as s:
        for rec in df.to_dict("records"):
            s.execute(
                update(Employee)
                .where(Employee.emp_id == rec["emp_id"])
                .values({k: _native(rec[k]) for k in fields})
            )
    return len(df)


def ingest_dataframe(
    df: pd.DataFrame, *, chunk_size: int | None = None, update_existing: bool = False,
) -> dict:
    """Validate an in-memory frame against the Employee schema and load the
    conforming rows. Returns a report: received / added / updated /
    skipped_duplicate / dropped_invalid.

    Rows are dropped when a required (NOT NULL) value is missing/unparseable.
    Rows whose emp_id already exists are, by default, skipped (append-only). With
    ``update_existing=True`` they instead overwrite the stored row (upsert on
    emp_id). A brand-new emp_id whose email already belongs to a *different*
    employee is always skipped, since the unique email constraint would reject it."""
    create_schema()

    received = len(df)
    df = _coerce_to_schema(df)  # raises SchemaMismatch on missing columns

    # Drop rows missing any required value (all business columns are NOT NULL).
    df = df.dropna(subset=REQUIRED_COLUMNS)
    dropped_invalid = received - len(df)

    empty_report = {"received": received, "added": 0, "updated": 0,
                    "skipped_duplicate": 0, "dropped_invalid": dropped_invalid}
    if df.empty:
        return empty_report

    # Normalise now that nulls are gone.
    df["emp_id"] = df["emp_id"].astype(str).str.strip()
    df["email"] = df["email"].astype(str).str.strip()
    df["date_of_joining"] = df["date_of_joining"].dt.date
    df["age"] = df["age"].round().astype(int)

    # De-dupe within the upload (keep first), then classify against the DB.
    deduped = df.drop_duplicates(subset="emp_id").drop_duplicates(subset="email")
    existing_ids, existing_emails = _existing_keys()
    is_existing = deduped["emp_id"].isin(existing_ids)

    # New emp_ids can only be inserted if their email isn't already taken by a
    # different employee.
    new_rows = deduped[~is_existing]
    insertable = new_rows[~new_rows["email"].isin(existing_emails)]

    chunk_size = chunk_size or config.INGEST_CHUNK_SIZE
    added = _bulk_insert(insertable, chunk_size)
    updated = _bulk_update(deduped[is_existing]) if update_existing else 0

    if added:
        _create_indexes()  # idempotent: CREATE INDEX IF NOT EXISTS

    # Everything conforming that we neither inserted nor updated was a duplicate
    # (within-file, an existing emp_id we didn't update, or an email clash).
    skipped_duplicate = len(df) - added - updated

    return {"received": received, "added": added, "updated": updated,
            "skipped_duplicate": skipped_duplicate,
            "dropped_invalid": dropped_invalid}
