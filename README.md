# Employee Master Dashboard — Service Layer

A Python dashboard over an employee master database, backed by CSV. This
repository contains the **framework-agnostic service layer** (data + logic).
The UI is deliberately decoupled and plugs in on top — Streamlit, or a custom
FastAPI + frontend — without touching any of this code.

> **Live demo:** deployed on **Streamlit Community Cloud**, backed by a
> **Supabase Postgres** database. _(Add your app URL here:
> `https://<your-app>.streamlit.app`.)_

It covers the four project requirements:

| Requirement | Where it lives |
|---|---|
| CSV as the data source | `scripts/generate_data.py` → `data/master.csv`, ingested by `employee_service/ingest.py` |
| Real-time updates | CRUD through `repository.py` persists to the DB; every query/chart reflects changes immediately |
| Interactive filters + visualization | `repository.list_employees` (filters, search, sort, pagination) + `distinct_values` for dropdowns; interactive **Plotly** charts on the Overview |
| Split any field by unique values, one click | `employee_service/splitter.py` |
| Export in ≥3 formats | `employee_service/exporter.py` — CSV, XLSX, JSON, Parquet |
| Bulk CSV upload | `app.py` **Bulk** page → `ingest.ingest_dataframe` — schema-validated, skip-or-upsert |

## Project structure

```
employee-dashboard/
├── README.md
├── requirements.txt
├── .env.example                # copy to .env and edit for your environment
├── .gitignore
│
├── app.py                      # Streamlit UI (Overview/Employees/Manage/Bulk), Plotly charts
├── .streamlit/config.toml      # UI theme
│
├── employee_service/           # the service layer (no UI framework imports)
│   ├── __init__.py
│   ├── config.py               # settings from env vars (DB URL, paths, limits)
│   ├── database.py             # SQLAlchemy engine + session factory + Base
│   ├── models.py               # Employee ORM model + column metadata
│   ├── dtos.py                 # PageResult (pagination DTO)
│   ├── exceptions.py           # domain exceptions
│   ├── ingest.py               # chunked CSV → DB load + bulk upload (validate + upsert)
│   ├── repository.py           # CRUD + filtered/paginated queries + SQL aggregates
│   ├── splitter.py             # split a field into per-value files / zip
│   └── exporter.py             # DataFrame → csv / xlsx / json / parquet bytes
│
├── scripts/
│   ├── generate_data.py        # Faker → master.csv (default 200k; --start-id to append)
│   └── seed_db.py              # master.csv → database (idempotent; --force to reload)
│
├── tests/
│   ├── test_repository.py      # CRUD + pagination + filter + whitelist + next emp_id
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
surface a FastAPI/custom frontend would use. Four pages, with a filter control bar
(department, designation, employment type, status, location, gender + free-text
search) applying across the Overview and Employees views:

- **Overview** — KPI band (headcount, active %, avg salary, avg rating) and
  interactive **Plotly** charts: donuts for categorical composition (status,
  employment type, gender), ranked bars (headcount by department/location, avg
  salary by department), and a joins-by-year area chart. Every value is computed
  with SQL aggregates (`repository.summary` / `aggregate_count` / `aggregate_avg` /
  `joins_by_year`), so nothing loads the full table — and the whole page loads
  through a single pooled connection (`get_overview_data`) behind a skeleton
  placeholder.
- **Employees** — the SQL-paginated table (sort + page controls), plus
  **Export current view** (any supported format, all matching rows) and
  **Split into files** (field + format → downloadable zip, with the group-count
  guardrail surfaced as a friendly warning).
- **Manage** — add / edit / delete forms wired to `repository` CRUD. Writes bump
  a version counter that invalidates the cached reads, so KPIs, charts, and the
  table reflect changes on the next interaction — this is the "real-time update"
  requirement, driven by CRUD rather than a background feed.
- **Bulk** — upload one or more CSVs; conforming rows are appended (or upserted).
  See [Bulk upload](#bulk-upload) below.

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
- **Prod (this deployment): Supabase Postgres** —
  `postgresql+psycopg2://…@…supabase.com:5432/postgres?sslmode=require`
- Prod (alt, keeps SQLite semantics): Turso / libSQL

No query or model code changes. The one dependency to add for Postgres is a
driver — `psycopg2-binary` (see `requirements.txt`).

**Fast loads.** Indexes are created *after* the bulk insert (`ingest.py`), so
loading an unindexed table stays fast and the index is built once.

**Never renders 200k rows.** `list_employees` counts and slices in SQL
(`LIMIT/OFFSET`), so the UI only ever holds one page.

**Charts aggregate in SQL, on one connection.** KPIs and every Overview chart come
from SQL `GROUP BY` aggregates (`summary` / `aggregate_count` / `aggregate_avg` /
`joins_by_year`) — even the hiring trend is `GROUP BY EXTRACT(year …)`, so no raw
rows cross the wire. The Overview bundles all of them into a single cached
connection (`get_overview_data`), which matters against a remote Postgres where
each connection is a network round-trip.

**Injection-safe dynamic columns.** Filters, sort, and split all reference
columns by name; every name is validated against `FIELD_COLUMNS` before it
reaches SQL.

## Export & split

Supported formats: `csv`, `xlsx`, `json`, `parquet` (add one row to
`exporter.FORMATS` to support more). The split feature takes a **field + a
format**, writes one file per unique value, and can hand back a single zip.
A safety limit (`MAX_SPLIT_GROUPS`, default 500) prevents accidentally splitting
on a high-cardinality column like `emp_id`.

## Bulk upload

The **Bulk** page (backed by `ingest.ingest_dataframe`) loads arbitrary CSVs into
the database:

- **Schema-validated.** A CSV must contain every business column (see the exact
  header list on the page). Missing columns raise a friendly error; extra columns
  are ignored; rows with a missing/unparseable required value are dropped.
- **Add-only by default.** New `emp_id`s are inserted. Rows whose `emp_id` already
  exists are **skipped** — existing data is never silently overwritten. A brand-new
  `emp_id` whose `email` already belongs to a different employee is also skipped
  (the unique constraint would reject it).
- **Optional upsert.** Tick **"Update existing employees"** to instead overwrite
  matching `emp_id` rows with the uploaded values.
- **Per-file report.** Each file reports `added / updated / skipped_duplicate /
  dropped_invalid`, and a successful load refreshes every KPI, chart, and filter.

Because IDs are unique, appending a *fresh* batch means generating non-overlapping
`emp_id`s. `generate_data.py` supports this:

```bash
# continue the sequence after the current DB max, automatically
python scripts/generate_data.py -n 20000 --seed 62 --start-id auto -o data/new_hires.csv
# ...or set the first id explicitly (e.g. past an existing 200k table)
python scripts/generate_data.py -n 20000 --start-id 200001 -o data/new_hires.csv
```

Then upload `data/new_hires.csv` on the Bulk page. (`--start-id auto` reads the DB
that `DATABASE_URL` points at, so export it to Supabase first if that's the target.)

## Deployment

Live on **Streamlit Community Cloud** with the database on **Supabase Postgres**.
The app container is stateless — all data lives in Supabase, so redeploys never
lose anything (no ephemeral-SQLite trap).

### 1. Create the Supabase database

1. Create a project at [supabase.com](https://supabase.com) and grab the
   connection string from **Project Settings → Database → Connection string**.
2. Streamlit Community Cloud is **IPv4-only**, while Supabase's *direct* host
   (`db.<ref>.supabase.co:5432`) is IPv6-only — use the **Session pooler** host
   instead (also port `5432`, IPv4-reachable). Format it for SQLAlchemy + psycopg2
   and append `sslmode=require`:

   ```
   postgresql+psycopg2://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
   ```

### 2. Seed it (one time, from your machine)

Point local `DATABASE_URL` at Supabase and run the generator + seeder — schema
creation and post-load indexing are handled by `ingest.py`:

```bash
export DATABASE_URL="postgresql+psycopg2://…:5432/postgres?sslmode=require"
python scripts/generate_data.py -n 200000
python scripts/seed_db.py
```

### 3. Deploy the app

1. Ensure the Postgres driver is installed on the host — `psycopg2-binary` must be
   present in `requirements.txt` (uncomment it if it isn't).
2. Push to GitHub, then on [share.streamlit.io](https://share.streamlit.io) create
   an app pointing at this repo with `app.py` as the entrypoint.
3. In the app's **Settings → Secrets**, set `DATABASE_URL` (Streamlit exposes
   secrets as environment variables, which `config.py` reads via `os.getenv`):

   ```toml
   DATABASE_URL = "postgresql+psycopg2://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require"
   ```

That's it — the app boots against Supabase, and `current_count()` gates the UI
until the table is seeded.