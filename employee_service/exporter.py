"""Serialize a DataFrame to any supported format, returning bytes. Returning
bytes (not writing files) keeps this usable both for on-disk output and for a
UI download button, and keeps the split feature a single code path."""
from __future__ import annotations

import io

import pandas as pd

from .exceptions import UnsupportedFormat


def _to_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def _to_json(df: pd.DataFrame) -> bytes:
    return df.to_json(orient="records", date_format="iso", indent=2).encode("utf-8")


def _to_xlsx(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="employees")
    return buf.getvalue()


def _to_parquet(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)  # requires pyarrow
    return buf.getvalue()


# Registry: format -> serializer, file extension, MIME type (handy for a UI
# download button). Add a new row here to support another format everywhere.
FORMATS: dict[str, dict] = {
    "csv":     {"fn": _to_csv,     "ext": "csv",     "mime": "text/csv"},
    "xlsx":    {"fn": _to_xlsx,    "ext": "xlsx",
                "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "json":    {"fn": _to_json,    "ext": "json",    "mime": "application/json"},
    "parquet": {"fn": _to_parquet, "ext": "parquet", "mime": "application/octet-stream"},
}


def supported_formats() -> list[str]:
    return list(FORMATS)


def _fmt(fmt: str) -> dict:
    key = fmt.lower()
    if key not in FORMATS:
        raise UnsupportedFormat(
            f"Unsupported format {fmt!r}. Choose from: {', '.join(FORMATS)}"
        )
    return FORMATS[key]


def to_bytes(df: pd.DataFrame, fmt: str) -> bytes:
    return _fmt(fmt)["fn"](df)


def extension(fmt: str) -> str:
    return _fmt(fmt)["ext"]


def mimetype(fmt: str) -> str:
    return _fmt(fmt)["mime"]
