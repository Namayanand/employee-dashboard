"""Employee Master — Streamlit prototype.

A thin UI over `employee_service` (imports only its public functions — the same
surface a FastAPI/custom frontend would use).

Layout:
  * Left rail  : Overview / Employees / Manage navigation, collapsible to icons.
  * Central    : a Filters & sorting control bar, then the selected page.

Run:  streamlit run app.py   (generate + seed data first — see README)
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_option_menu import option_menu

from employee_service import config, exporter, repository as repo, splitter
from employee_service.database import session_scope
from employee_service.exceptions import (
    EmployeeNotFound,
    EmployeeServiceError,
    TooManyGroups,
)
from employee_service.ingest import current_count

st.set_page_config(
    page_title="Employee Master", page_icon="●",
    layout="wide", initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      .block-container {padding-top:1rem !important; padding-bottom:2rem !important;padding-left: 2rem !important; padding-right: 2rem !important;}
      [data-testid="stMetric"] {background:#fff; border:1px solid #E7E8EF;
        border-radius:12px; padding:16px 18px; min-height:120px;}
      [data-testid="stMetricValue"] {font-size:1.7rem;}
      /* rail buttons: a touch taller, rounded */
      div[data-testid="stButton"] > button {border-radius:10px;}
    </style>
    """,
    unsafe_allow_html=True,
)

FILTER_COLUMNS = ["department", "designation", "employment_type",
                  "status", "location", "gender"]
SPLIT_DEFAULT = "department"
PAGES = ["Overview", "Employees", "Manage"]
BS_ICONS = ["bar-chart-fill", "people-fill", "tools"]   # option_menu (expanded)
EMOJI = {"Overview": "📊", "Employees": "👥", "Manage": "🛠"}  # buttons (collapsed)

NAV_STYLES = {
    "container": {"padding": "6px", "background-color": "#F1F2F6",
                  "border-radius": "12px"},
    "nav-link": {"font-size": "15px", "padding": "10px 14px",
                 "border-radius": "8px", "--hover-color": "#9572B8"},
    "nav-link-selected": {"background-color": "#68458A", "color": "white"},
    "icon": {"font-size": "15px"},
}


# --------------------------------------------------------------------------- #
# State helpers (a version counter invalidates cached reads after any write)
# --------------------------------------------------------------------------- #
def data_version() -> int:
    return st.session_state.setdefault("data_version", 0)


def bump_version() -> None:
    st.session_state["data_version"] = data_version() + 1


def filters_key(filters: dict) -> tuple:
    return tuple(sorted((k, tuple(v)) for k, v in filters.items()))


# --------------------------------------------------------------------------- #
# Cached data access
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def options_for(column: str, _version: int) -> list:
    with session_scope() as s:
        return repo.distinct_values(s, column)


@st.cache_data(show_spinner=False)
def get_summary(fkey: tuple, search: str, _version: int) -> dict:
    with session_scope() as s:
        return repo.summary(s, filters=dict(fkey), search=search or None)


@st.cache_data(show_spinner=False)
def get_counts(column: str, fkey: tuple, search: str, _version: int) -> pd.DataFrame:
    with session_scope() as s:
        rows = repo.aggregate_count(s, column, filters=dict(fkey), search=search or None)
    return pd.DataFrame(rows, columns=[column, "count"])


@st.cache_data(show_spinner=False)
def get_joins_by_year(fkey: tuple, search: str, _version: int) -> pd.DataFrame:
    with session_scope() as s:
        df = repo.query_dataframe(s, filters=dict(fkey), search=search or None,
                                  columns=["date_of_joining"])
    if df.empty:
        return pd.DataFrame({"year": [], "count": []})
    year = pd.to_datetime(df["date_of_joining"]).dt.year
    return year.value_counts().sort_index().rename_axis("year").reset_index(name="count")


def get_page(filters, search, sort_by, sort_dir, page, page_size):
    with session_scope() as s:
        return repo.list_employees(s, filters=filters, search=search or None,
                                   sort_by=sort_by, sort_dir=sort_dir,
                                   page=page, page_size=page_size)


def get_filtered_df(filters, search) -> pd.DataFrame:
    with session_scope() as s:
        return repo.query_dataframe(s, filters=filters, search=search or None)


# --------------------------------------------------------------------------- #
# Central control bar — filters + sorting (was the sidebar)
# --------------------------------------------------------------------------- #
def control_bar(show_sort: bool) -> tuple[dict, str, str, str, int]:
    v = data_version()
    filters: dict = {}
    with st.expander("Filters & sorting", expanded=True):
        grid = st.columns(3)
        for i, col in enumerate(FILTER_COLUMNS):
            chosen = grid[i % 3].multiselect(
                col.replace("_", " ").title(), options_for(col, v), key=f"f_{col}"
            )
            if chosen:
                filters[col] = chosen

        st.markdown("")
        if show_sort:
            row = st.columns([3, 2, 1.3, 1.3])
            search = row[0].text_input("Search", key="q",
                                       placeholder="name, email, emp id…")
            cols = repo.field_columns()
            sort_by = row[1].selectbox("Sort by", cols,
                                       index=cols.index("emp_id"), key="sort_by")
            sort_dir = row[2].selectbox("Order", ["asc", "desc"], key="sort_dir")
            page_size = row[3].selectbox("Rows/page", [25, 50, 100, 200],
                                         index=1, key="rows")
        else:
            search = st.text_input("Search", key="q",
                                   placeholder="name, email, emp id…")
            sort_by, sort_dir, page_size = "emp_id", "asc", 50

        spacer, clear = st.columns([6, 1])
        if clear.button("Clear", use_container_width=True):
            for col in FILTER_COLUMNS:
                st.session_state.pop(f"f_{col}", None)
            st.session_state.pop("q", None)
            st.rerun()

    return filters, search.strip(), sort_by, sort_dir, page_size


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
def page_overview(fkey: tuple, search: str, v: int):
    kpis = get_summary(fkey, search, v)
    head = kpis["headcount"]
    active_pct = (kpis["active"] / head * 100) if head else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Headcount", f"{head:,}")
    c2.metric("Active", f"{kpis['active']:,}", f"{active_pct:.0f}% of total")
    c3.metric("Avg salary", f"₹{kpis['avg_salary']:,.0f}")
    c4.metric("Avg rating", f"{kpis['avg_rating']:.2f} / 5")

    if head == 0:
        st.info("No employees match these filters. Clear a filter to see results.")
        return

    st.divider()
    left, right = st.columns(2)
    with left:
        st.caption("Headcount by department")
        with st.container(border=True):
            st.bar_chart(get_counts("department", fkey, search, v).set_index("department"),color='#68458A')
    with right:
        st.caption("Headcount by location")
        with st.container(border=True):
            st.bar_chart(get_counts("location", fkey, search, v).set_index("location"),color='#68458A')

    st.caption("Joins by year")
    with st.container(border=True):
        joins = get_joins_by_year(fkey, search, v)
        if not joins.empty:
            st.line_chart(joins.set_index("year"),color='#68458A')


def page_employees(filters, search, fkey, v, sort_by, sort_dir, page_size):
    nav = st.columns([1, 3])
    page = nav[0].number_input("Page", min_value=1, value=1, step=1, key="emp_page")

    result = get_page(filters, search, sort_by, sort_dir, int(page), page_size)
    if result.total == 0:
        st.info("Nothing to show yet. Adjust the filters above.")
        return

    nav[1].markdown(
        f"<div style='padding-top:1.9rem;color:#5b6070'>Page {result.page} of "
        f"{result.pages} · {result.total:,} match</div>", unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(result.items), use_container_width=True, hide_index=True)

    st.divider()
    export_and_split(filters, search, fkey, v)


def export_and_split(filters, search, fkey, v):
    ex, sp = st.columns(2)
    with ex:
        st.subheader("Export current view")
        st.caption("Exports every matching row, not just this page.")
        fmt = st.selectbox("Format", exporter.supported_formats(), key="exp_fmt")
        if st.button("Prepare export", key="exp_go"):
            df = get_filtered_df(filters, search)
            st.session_state["export_blob"] = exporter.to_bytes(df, fmt)
            st.session_state["export_meta"] = (fmt, len(df))
        if "export_blob" in st.session_state:
            fmt_done, n = st.session_state["export_meta"]
            st.download_button(
                f"Download {n:,} rows (.{exporter.extension(fmt_done)})",
                st.session_state["export_blob"],
                file_name=f"employees.{exporter.extension(fmt_done)}",
                mime=exporter.mimetype(fmt_done))

    with sp:
        st.subheader("Split into files")
        field = st.selectbox("Split by field", repo.field_columns(),
                             index=repo.field_columns().index(SPLIT_DEFAULT), key="sp_field")
        sfmt = st.selectbox("File format", exporter.supported_formats(), key="sp_fmt")
        n_groups = len(options_for(field, v)) if field in FILTER_COLUMNS else "many"
        st.caption(f"One {sfmt.upper()} per unique value ({n_groups} for the full table).")
        if st.button("Split into files", key="sp_go"):
            df = get_filtered_df(filters, search)
            try:
                st.session_state["split_zip"] = splitter.split_to_zip(df, field, sfmt)
                st.session_state["split_meta"] = (field, sfmt)
            except TooManyGroups as e:
                st.session_state.pop("split_zip", None)
                st.warning(str(e))
        if "split_zip" in st.session_state:
            f, sf = st.session_state["split_meta"]
            st.download_button(f"Download split_by_{f}.zip", st.session_state["split_zip"],
                               file_name=f"split_by_{f}_{sf}.zip", mime="application/zip")


EDITABLE = [c for c in repo.field_columns() if c != "emp_id"]


def page_manage(v: int):
    st.caption("Create, update, or remove employees. Changes persist immediately "
               "and refresh every filter, chart, and KPI.")
    add, edit, remove = st.tabs(["Add", "Edit", "Delete"])

    with add:
        with st.form("add_form", clear_on_submit=True):
            emp_id = st.text_input("Employee ID", placeholder="EMP200001")
            vals = _field_inputs({}, v, key_prefix="add")
            if st.form_submit_button("Add employee"):
                _do_write(lambda s: repo.create_employee(s, {"emp_id": emp_id, **vals}),
                          f"Added {emp_id}.")

    with edit:
        emp_id = st.text_input("Employee ID to edit", key="edit_id")
        if emp_id:
            try:
                with session_scope() as s:
                    current = repo.get_employee(s, emp_id).to_dict()
            except EmployeeNotFound:
                st.info(f"No employee with ID {emp_id}.")
                current = None
            if current:
                with st.form("edit_form"):
                    vals = _field_inputs(current, v, key_prefix="edit")
                    if st.form_submit_button("Save changes"):
                        _do_write(lambda s: repo.update_employee(s, emp_id, vals),
                                  f"Updated {emp_id}.")

    with remove:
        emp_id = st.text_input("Employee ID to delete", key="del_id")
        st.caption("This can't be undone.")
        if st.button("Delete employee", type="primary"):
            _do_write(lambda s: repo.delete_employee(s, emp_id), f"Deleted {emp_id}.")


def _field_inputs(current: dict, v: int, key_prefix: str) -> dict:
    out: dict = {}
    grid = st.columns(2)
    for i, col in enumerate(EDITABLE):
        widget = grid[i % 2]
        label = col.replace("_", " ").title()
        key = f"{key_prefix}_{col}"
        if col in FILTER_COLUMNS:
            opts = options_for(col, v)
            idx = opts.index(current[col]) if current.get(col) in opts else 0
            out[col] = widget.selectbox(label, opts, index=idx, key=key)
        elif col == "age":
            out[col] = widget.number_input(label, 18, 75, int(current.get(col, 30)), key=key)
        elif col in ("salary", "performance_rating"):
            out[col] = widget.number_input(label, value=float(current.get(col, 0) or 0), key=key)
        elif col == "date_of_joining":
            val = pd.to_datetime(current.get(col)).date() if current.get(col) \
                else pd.Timestamp.today().date()
            out[col] = widget.date_input(label, val, key=key)
        else:
            out[col] = widget.text_input(label, value=str(current.get(col, "")), key=key)
    return out


def _do_write(action, success_msg: str):
    try:
        with session_scope() as s:
            action(s)
        bump_version()
        st.success(success_msg)
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't complete that: {e}")


# --------------------------------------------------------------------------- #
# Left rail (custom, column-based, collapsible to icons)
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    st.title("Employee Master")

    if current_count() == 0:
        st.warning("The database is empty. Generate and load data first:")
        st.code("python scripts/generate_data.py -n 200000\n"
                "python scripts/seed_db.py", language="bash")
        st.stop()

    st.caption(f"{current_count():,} employees · {config.DATABASE_URL.split('/')[-1]}")

    rail_col, content_col = st.columns([2.3, 10])
    with rail_col:
        selected = option_menu(
            menu_title=None,
            options=["Overview", "Employees", "Manage"],
            icons=["bar-chart-fill", "people-fill", "tools"],  # Bootstrap Icons
            default_index=0,
            key="nav_menu",
            styles=NAV_STYLES,
        )

    with content_col:
        v = data_version()
        if selected in ("Overview", "Employees"):
            filters, search, sort_by, sort_dir, page_size = control_bar(
                show_sort=(selected == "Employees"))
            fkey = filters_key(filters)
        if selected == "Overview":
            page_overview(fkey, search, v)
        elif selected == "Employees":
            page_employees(filters, search, fkey, v, sort_by, sort_dir, page_size)
        else:
            page_manage(v)
if __name__ == "__main__":
    main()
