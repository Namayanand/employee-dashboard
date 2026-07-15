"""CRUD + query tests. Because repository functions take an explicit Session,
we point them at a throwaway in-memory database — no fixtures, no real DB."""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from employee_service import repository as repo
from employee_service.database import Base
from employee_service.exceptions import EmployeeNotFound, InvalidColumn


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _sample(emp_id: str, department: str = "Engineering") -> dict:
    return {
        "emp_id": emp_id, "full_name": "Test User",
        "email": f"{emp_id}@example.com", "department": department,
        "designation": "Manager", "employment_type": "Full-time",
        "status": "Active", "location": "Pune", "gender": "Other",
        "date_of_joining": dt.date(2020, 1, 1), "age": 30,
        "salary": 1_000_000.0, "performance_rating": 4, "manager_name": "Boss",
    }


def test_create_and_get(session):
    repo.create_employee(session, _sample("EMP000001"))
    assert repo.get_employee(session, "EMP000001").full_name == "Test User"


def test_update(session):
    repo.create_employee(session, _sample("EMP000001"))
    repo.update_employee(session, "EMP000001", {"salary": 2_000_000.0})
    assert repo.get_employee(session, "EMP000001").salary == 2_000_000.0


def test_delete(session):
    repo.create_employee(session, _sample("EMP000001"))
    assert repo.delete_employee(session, "EMP000001") is True
    with pytest.raises(EmployeeNotFound):
        repo.get_employee(session, "EMP000001")


def test_list_pagination_and_filter(session):
    for i in range(1, 26):
        dept = "Engineering" if i % 2 else "Sales"
        repo.create_employee(session, _sample(f"EMP{i:06d}", dept))

    page1 = repo.list_employees(session, page=1, page_size=10)
    assert page1.total == 25 and len(page1.items) == 10 and page1.pages == 3

    eng = repo.list_employees(session, filters={"department": "Engineering"})
    assert eng.total == 13  # odd i -> Engineering, 1..25


def test_invalid_column_rejected(session):
    with pytest.raises(InvalidColumn):
        repo.list_employees(session, sort_by="drop table")
