"""Attest Cloud v0 — FastAPI + SQLAlchemy (Postgres in production, SQLite for tests/dev).

Every table carries `org_id`; every query is scoped by the API key's org. The ledger is hash-chained per org.
"""
__version__ = "0.1.0"
