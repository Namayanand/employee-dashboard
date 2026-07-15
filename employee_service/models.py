"""The Employee model plus the column metadata the service layer uses to stay
generic (which fields are filterable, searchable, indexed)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Employee(Base):
    __tablename__ = "employees"

    # Surrogate PK, internal only. `emp_id` is the business identifier.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    emp_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    department: Mapped[str] = mapped_column(String(60), nullable=False)
    designation: Mapped[str] = mapped_column(String(80), nullable=False)
    employment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    location: Mapped[str] = mapped_column(String(60), nullable=False)
    gender: Mapped[str] = mapped_column(String(20), nullable=False)
    date_of_joining: Mapped[dt.date] = mapped_column(Date, nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    salary: Mapped[float] = mapped_column(Float, nullable=False)
    performance_rating: Mapped[float] = mapped_column(Float, nullable=False)
    manager_name: Mapped[str] = mapped_column(String(120), nullable=False)

    def to_dict(self) -> dict:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


# Fields exposed to the UI/service (surrogate PK excluded). Used to whitelist
# every dynamic column reference (filter / sort / split) against SQL injection.
FIELD_COLUMNS: list[str] = [
    c.name for c in Employee.__table__.columns if c.name != "id"
]

# Indexes are created AFTER the bulk load (see ingest.py) so inserts stay fast.
INDEXED_COLUMNS: list[str] = [
    "emp_id", "department", "designation", "employment_type",
    "status", "location", "gender",
]

# Columns hit by the free-text search box.
SEARCHABLE_COLUMNS: list[str] = ["emp_id", "full_name", "email", "manager_name"]
