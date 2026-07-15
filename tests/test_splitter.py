"""Splitter tests — pure DataFrame logic, no database needed."""
from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest

from employee_service import splitter
from employee_service.exceptions import InvalidColumn, TooManyGroups


def _df() -> pd.DataFrame:
    return pd.DataFrame({
        "emp_id": ["E1", "E2", "E3", "E4"],
        "department": ["Sales", "Sales", "R&D", "R&D"],
        "location": ["Pune", "Pune", "Pune", "Delhi"],
    })


def test_split_produces_one_file_per_unique_value():
    files = splitter.split_dataframe(_df(), "department", "csv")
    assert len(files) == 2  # Sales, R&D


def test_filenames_are_sanitized():
    # "R&D" contains an unsafe char; it must not leak into the filename.
    files = splitter.split_dataframe(_df(), "department", "csv")
    assert all("&" not in name for name in files)


def test_unknown_column_rejected():
    with pytest.raises(InvalidColumn):
        splitter.split_dataframe(_df(), "salary_bracket", "csv")


def test_too_many_groups_guardrail():
    with pytest.raises(TooManyGroups):
        splitter.split_dataframe(_df(), "emp_id", "csv", max_groups=2)


def test_zip_bundle_contains_all_groups():
    blob = splitter.split_to_zip(_df(), "location", "csv")
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        assert len(zf.namelist()) == 2  # Pune, Delhi
