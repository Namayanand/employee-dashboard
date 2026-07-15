"""Framework-agnostic service layer for the employee dashboard.

Nothing in this package imports Streamlit / FastAPI / any UI framework. The UI
(whatever you choose later) drives the app purely through these modules:

    config      -> settings from env vars
    database    -> SQLAlchemy engine + session factory
    models      -> the Employee ORM model + column metadata
    ingest      -> chunked CSV -> DB load with post-load indexing
    repository  -> CRUD + paginated/filtered queries
    splitter    -> split any field's unique values into separate files
    exporter    -> serialize a DataFrame to csv / xlsx / json / parquet
"""

__version__ = "0.1.0"
