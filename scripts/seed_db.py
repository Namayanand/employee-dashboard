#!/usr/bin/env python
"""Load the master CSV into the database.

    python scripts/seed_db.py            # idempotent load
    python scripts/seed_db.py --force    # wipe + reload (drops any edits)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from employee_service import config, ingest  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest master CSV into the database.")
    ap.add_argument("--csv", default=str(config.MASTER_CSV))
    ap.add_argument("--chunk-size", type=int, default=config.INGEST_CHUNK_SIZE)
    ap.add_argument("--force", action="store_true",
                    help="Wipe existing rows and reload from CSV.")
    args = ap.parse_args()

    count = ingest.ingest_csv(args.csv, chunk_size=args.chunk_size, force=args.force)
    print(f"Database now holds {count:,} employees.")
    print(f"  DB : {config.DATABASE_URL}")


if __name__ == "__main__":
    main()
