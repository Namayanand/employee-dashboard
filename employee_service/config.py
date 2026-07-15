"""Central configuration. Everything is overridable via environment variables
(loaded from a local .env in development), so nothing about the deployment
target is hard-coded into the code."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", PROJECT_ROOT / "output"))

# Dev default: a local SQLite file. Swap this one string for prod:
#   Turso/libSQL : sqlite+libsql://<db>.turso.io?authToken=<token>&secure=true
#   Postgres     : postgresql+psycopg2://user:pass@host:5432/dbname
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'employees.db'}")

MASTER_CSV = Path(os.getenv("MASTER_CSV", DATA_DIR / "master.csv"))

DEFAULT_PAGE_SIZE = int(os.getenv("DEFAULT_PAGE_SIZE", "50"))
MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", "500"))
INGEST_CHUNK_SIZE = int(os.getenv("INGEST_CHUNK_SIZE", "10000"))

# Safety rail for the split feature: refuse to explode into more than N files
# (e.g. someone splits on emp_id and asks for 200k files).
MAX_SPLIT_GROUPS = int(os.getenv("MAX_SPLIT_GROUPS", "500"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
