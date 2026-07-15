# Employee Master Dashboard — Service Layer

A Python dashboard over an employee master database, backed by CSV. This
repository contains the **framework-agnostic service layer** (data + logic).
The UI is deliberately decoupled and plugs in on top — Streamlit, or a custom
FastAPI + frontend — without touching any of this code.

It covers the four project requirements:

| Requirement | Where it lives |
|---|---|
| CSV as the data source | `scripts/generate_data.py` → `data/master.csv`, ingested by `employee_service/ingest.py` |
| Real-time updates | CRUD through `repository.py` persists to the DB; every query/chart reflects changes immediately |
| Interactive filters + visualization | `repository.list_employees` (filters, search, sort, pagination) + `distinct_values` for dropdowns |
| Split any field by unique values, one click | `employee_service/splitter.py` |
| Export in ≥3 formats | `employee_service/exporter.py` — CSV, XLSX, JSON, Parquet |

## Project structure

```
employee-dashboard/
├── README.md
├── requirements.txt
├── .env.example                # copy to .env and edit for your environment
├── .gitignore
│
├── app.py                      # Streamlit UI prototype (calls employee_service only)
├── .streamlit/config.toml      # UI theme
│
├── employee_service/           # the service layer (no UI framework imports)
│   ├── __init__.py
│   ├── config.py               # settings from env vars (DB URL, paths, limits)
│   ├── database.py             # SQLAlchemy engine + session factory + Base
│   ├── models.py               # Employee ORM model + column metadata
│   ├── dtos.py                 # PageResult (pagination DTO)
│   ├── exceptions.py           # domain exceptions
│   ├── ingest.py               # chunked CSV → DB load, post-load indexing
│   ├── repository.py           # CRUD + filtered/paginated queries
│   ├── splitter.py             # split a field into per-value files / zip
│   └── exporter.py             # DataFrame → csv / xlsx / json / parquet bytes
│
├── scripts/
│   ├── generate_data.py        # Faker → master.csv (default 200k rows)
│   └── seed_db.py              # master.csv → database (idempotent; --force to reload)
│
├── tests/
│   ├── test_repository.py      # CRUD + pagination + filter + column whitelist
│   └── test_splitter.py        # split counts, filename safety, guardrails
│
├── data/                       # master.csv + local SQLite db land here (gitignored)
└── output/                     # exports & split files land here (gitignored)
```

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

python scripts/generate_data.py -n 200000    # write data/master.csv
python scripts/seed_db.py                    # load it into the database
pytest -q                                    # sanity check
streamlit run app.py                         # launch the dashboard
```

## The UI (`app.py`)

A Streamlit prototype that imports only the public service functions — the same
surface a FastAPI/custom frontend would use. Three tabs, with sidebar filters
(department, designation, employment type, status, location, gender + free-text
search) applying across all of them:

- **Overview** — KPI band (headcount, active %, avg salary, avg rating) and
  charts (headcount by department/location, joins by year). KPIs and category
  charts are computed with SQL `GROUP BY` (`repository.summary` /
  `repository.aggregate_count`), so nothing loads the full table.
- **Employees** — the SQL-paginated table (sort + page controls), plus
  **Export current view** (any supported format, all matching rows) and
  **Split into files** (field + format → downloadable zip, with the group-count
  guardrail surfaced as a friendly warning).
- **Manage** — add / edit / delete forms wired to `repository` CRUD. Writes bump
  a version counter that invalidates the cached reads, so KPIs, charts, and the
  table reflect changes on the next interaction — this is the "real-time update"
  requirement, driven by CRUD rather than a background feed.

Then drive it from any UI or a REPL:

```python
from employee_service import repository as repo, splitter, exporter
from employee_service.database import session_scope

with session_scope() as s:
    # paginated, filtered, sorted page for a table view
    page = repo.list_employees(
        s, filters={"department": "Engineering", "status": "Active"},
        search="sharma", sort_by="salary", sort_dir="desc", page=1, page_size=50,
    )
    page.items, page.total, page.pages          # rows + pagination metadata

    repo.distinct_values(s, "location")          # populate a filter dropdown

    # export / split operate on "what you're currently looking at"
    df = repo.query_dataframe(s, filters={"department": "Sales"})
    exporter.to_bytes(df, "xlsx")                # download bytes in any format
    splitter.split_to_zip(df, "location", "csv") # one-click split → zip of files
```

## Architecture notes

**CSV stays the source; SQLite is the operational store.** The CSV is the
canonical input/export format; on first run it's ingested into a database that
serves the actual CRUD and filtering. This keeps the "CSV as data source"
requirement intact while giving you indexed, transactional operations and
pagination at 100k–200k rows.

**One-line dev→prod database swap.** Everything goes through SQLAlchemy, so the
only thing that changes between local dev and production is `DATABASE_URL`:

- Dev: `sqlite:///./data/employees.db`
- Prod (keeps SQLite semantics, hosted): Turso / libSQL
- Prod (Postgres): Supabase or a managed instance

No query or model code changes.

**Fast loads.** Indexes are created *after* the bulk insert (`ingest.py`), so
loading an unindexed table stays fast and the index is built once.

**Never renders 200k rows.** `list_employees` counts and slices in SQL
(`LIMIT/OFFSET`), so the UI only ever holds one page.

**Injection-safe dynamic columns.** Filters, sort, and split all reference
columns by name; every name is validated against `FIELD_COLUMNS` before it
reaches SQL.

## Export & split

Supported formats: `csv`, `xlsx`, `json`, `parquet` (add one row to
`exporter.FORMATS` to support more). The split feature takes a **field + a
format**, writes one file per unique value, and can hand back a single zip.
A safety limit (`MAX_SPLIT_GROUPS`, default 500) prevents accidentally splitting
on a high-cardinality column like `emp_id`.

## Deployment (optional)

Deployment isn't required by the brief — a clean local run plus this README is a
complete submission. If you do host it:

- **The trap:** Railway/most hosts have an *ephemeral filesystem*. A SQLite file
  on the container disk is wiped on every redeploy. Either attach a **persistent
  volume** for the `.db` file, or use a hosted DB (Turso / Supabase Postgres) via
  `DATABASE_URL`.
- Railway is no longer free for an always-on app + DB (≈$5/mo). For a genuinely
  free hosted demo, run the app on a free tier and point `DATABASE_URL` at a free
  managed database.

## Roadmap

- [x] UI layer (Streamlit prototype in `app.py`, calling only `employee_service`)
- [x] Charts/KPIs via SQL aggregates (`repository.summary` / `aggregate_count`)
- [ ] Inline-edit grid (`st.data_editor`) as an alternative to the CRUD forms
- [ ] Swap native charts for Plotly (nicer tooltips/interactivity)
- [ ] PDF export as a 5th format (report-style)
- [ ] Optional deploy with a persistent DB backend
