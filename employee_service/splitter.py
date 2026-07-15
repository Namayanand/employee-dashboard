"""The headline feature: pick any field, split the (filtered) data into one file
per unique value. Reuses the exporter, so it works in every supported format."""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pandas as pd

from . import config, exporter
from .exceptions import InvalidColumn, TooManyGroups
from .models import FIELD_COLUMNS

# Anything that isn't filename-safe collapses to underscore.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(value) -> str:
    """Turn an arbitrary cell value into a safe filename fragment."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        text = "NULL"
    else:
        text = str(value).strip()
    text = _UNSAFE.sub("_", text).strip("._")
    return text or "NULL"


def split_dataframe(
    df: pd.DataFrame, column: str, fmt: str = "csv", *, max_groups: int | None = None
) -> dict[str, bytes]:
    """Return {filename: bytes} — one entry per unique value of `column`."""
    if column not in FIELD_COLUMNS:
        raise InvalidColumn(f"Cannot split on unknown column: {column!r}")
    max_groups = max_groups or config.MAX_SPLIT_GROUPS

    groups = df.groupby(column, dropna=False)
    if groups.ngroups > max_groups:
        raise TooManyGroups(
            f"Splitting on {column!r} would create {groups.ngroups} files "
            f"(limit {max_groups}). Filter first or raise MAX_SPLIT_GROUPS."
        )

    ext = exporter.extension(fmt)
    out: dict[str, bytes] = {}
    seen: dict[str, int] = {}
    for value, group in groups:
        name = _safe_name(value)
        if name in seen:  # two distinct values sanitized to the same string
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        out[f"{column}={name}.{ext}"] = exporter.to_bytes(group, fmt)
    return out


def split_to_zip(
    df: pd.DataFrame, column: str, fmt: str = "csv", *, max_groups: int | None = None
) -> bytes:
    """Bundle the split into a single downloadable zip (bytes)."""
    files = split_dataframe(df, column, fmt, max_groups=max_groups)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def split_to_dir(
    df: pd.DataFrame,
    column: str,
    fmt: str = "csv",
    out_dir: str | Path | None = None,
    *,
    max_groups: int | None = None,
) -> list[str]:
    """Write the split files to disk; return the paths written."""
    out_dir = Path(out_dir or (config.OUTPUT_DIR / f"split_by_{column}"))
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, data in split_dataframe(df, column, fmt, max_groups=max_groups).items():
        path = out_dir / name
        path.write_bytes(data)
        paths.append(str(path))
    return paths
