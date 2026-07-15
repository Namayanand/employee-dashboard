"""CRUD + query logic. Every function takes an explicit Session, so it works
identically against the app's real engine and against a throwaway test session.
All dynamic column names are validated against FIELD_COLUMNS before touching SQL."""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd
from sqlalchemy import asc, case, desc, func, or_, select
from sqlalchemy.orm import Session

from . import config
from .dtos import PageResult
from .exceptions import EmployeeNotFound, InvalidColumn
from .models import FIELD_COLUMNS, SEARCHABLE_COLUMNS, Employee

_ALLOWED = set(FIELD_COLUMNS)


def field_columns() -> list[str]:
    """Columns a UI can filter/sort/split on."""
    return list(FIELD_COLUMNS)


def _column(name: str):
    if name not in _ALLOWED:
        raise InvalidColumn(f"Unknown column: {name!r}")
    return getattr(Employee, name)


def _apply_filters(stmt, filters: Optional[dict], search: Optional[str]):
    """filters: {column: value} for equality, or {column: [v1, v2]} for IN.
    search: free-text matched (case-insensitive) across SEARCHABLE_COLUMNS."""
    if filters:
        for col, value in filters.items():
            column = _column(col)
            if isinstance(value, (list, tuple, set)):
                values = [v for v in value if v not in (None, "")]
                if values:
                    stmt = stmt.where(column.in_(values))
            elif value not in (None, ""):
                stmt = stmt.where(column == value)
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(*[getattr(Employee, c).ilike(term) for c in SEARCHABLE_COLUMNS])
        )
    return stmt


def _order(stmt, sort_by: str, sort_dir: str):
    col = _column(sort_by)
    return stmt.order_by(desc(col) if str(sort_dir).lower() == "desc" else asc(col))


# --------------------------------------------------------------------------- #
# Create / Read / Update / Delete
# --------------------------------------------------------------------------- #
def create_employee(session: Session, data: dict[str, Any]) -> Employee:
    payload = {k: v for k, v in data.items() if k in _ALLOWED}
    emp = Employee(**payload)
    session.add(emp)
    session.flush()  # assign PK and surface integrity errors immediately
    return emp


def get_employee(session: Session, emp_id: str) -> Employee:
    emp = session.scalar(select(Employee).where(Employee.emp_id == emp_id))
    if emp is None:
        raise EmployeeNotFound(f"No employee with emp_id={emp_id!r}")
    return emp


def update_employee(session: Session, emp_id: str, data: dict[str, Any]) -> Employee:
    emp = get_employee(session, emp_id)
    for key, value in data.items():
        if key in _ALLOWED and key != "emp_id":  # emp_id is immutable
            setattr(emp, key, value)
    session.flush()
    return emp


def delete_employee(session: Session, emp_id: str) -> bool:
    session.delete(get_employee(session, emp_id))
    session.flush()
    return True


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #
def list_employees(
    session: Session,
    *,
    filters: Optional[dict] = None,
    search: Optional[str] = None,
    sort_by: str = "emp_id",
    sort_dir: str = "asc",
    page: int = 1,
    page_size: Optional[int] = None,
) -> PageResult:
    """One page of results. Count + slice happen in SQL, so this stays fast at
    200k rows because we never pull the whole table into memory."""
    page = max(1, int(page))
    page_size = min(int(page_size or config.DEFAULT_PAGE_SIZE), config.MAX_PAGE_SIZE)

    filtered = _apply_filters(select(Employee), filters, search)
    total = session.scalar(select(func.count()).select_from(filtered.subquery())) or 0

    stmt = _order(filtered, sort_by, sort_dir).offset((page - 1) * page_size).limit(page_size)
    rows = session.scalars(stmt).all()
    return PageResult([r.to_dict() for r in rows], total, page, page_size)


def distinct_values(session: Session, column: str) -> list:
    """Unique values of a column — for filter dropdowns and split previews."""
    col = _column(column)
    return [r[0] for r in session.execute(select(col).distinct().order_by(col)).all()]


def query_dataframe(
    session: Session,
    *,
    filters: Optional[dict] = None,
    search: Optional[str] = None,
    sort_by: str = "emp_id",
    sort_dir: str = "asc",
    columns: Optional[list[str]] = None,
) -> pd.DataFrame:
    """The full filtered result set as a DataFrame (no pagination). This is what
    feeds export and split — 'export/split what you're currently looking at'."""
    selected = columns or FIELD_COLUMNS
    for c in selected:
        _column(c)  # validate
    stmt = _order(_apply_filters(select(*[getattr(Employee, c) for c in selected]),
                                 filters, search), sort_by, sort_dir)
    return pd.read_sql(stmt, session.connection())


# --------------------------------------------------------------------------- #
# Aggregates (computed in SQL — the charts/KPIs never load the full table)
# --------------------------------------------------------------------------- #
def aggregate_count(
    session: Session,
    group_by: str,
    *,
    filters: Optional[dict] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[tuple[Any, int]]:
    """[(value, count), ...] for a column, honouring the active filters."""
    col = _column(group_by)
    stmt = _apply_filters(select(col, func.count().label("n")), filters, search)
    stmt = stmt.group_by(col).order_by(func.count().desc())
    if limit:
        stmt = stmt.limit(limit)
    return [(r[0], int(r[1])) for r in session.execute(stmt).all()]


def aggregate_avg(
    session: Session,
    group_by: str,
    value_col: str,
    *,
    filters: Optional[dict] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[tuple[Any, float]]:
    """[(value, avg), ...] — average of `value_col` per group, honouring filters."""
    col = _column(group_by)
    val = _column(value_col)
    stmt = _apply_filters(select(col, func.avg(val).label("avg")), filters, search)
    stmt = stmt.group_by(col).order_by(func.avg(val).desc())
    if limit:
        stmt = stmt.limit(limit)
    return [(r[0], float(r[1] or 0.0)) for r in session.execute(stmt).all()]


def summary(
    session: Session,
    *,
    filters: Optional[dict] = None,
    search: Optional[str] = None,
) -> dict:
    """Headline KPIs for the current filter set, in one query."""
    stmt = _apply_filters(
        select(
            func.count().label("headcount"),
            func.sum(case((Employee.status == "Active", 1), else_=0)).label("active"),
            func.avg(Employee.salary).label("avg_salary"),
            func.avg(Employee.performance_rating).label("avg_rating"),
        ),
        filters,
        search,
    )
    row = session.execute(stmt).one()
    return {
        "headcount": int(row.headcount or 0),
        "active": int(row.active or 0),
        "avg_salary": float(row.avg_salary or 0.0),
        "avg_rating": float(row.avg_rating or 0.0),
    }
