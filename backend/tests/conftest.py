import os

import pytest

from app import create_app
from app.salesforce import MockSalesforce

# CI sets TEST_DATABASE_URL to a real PostgreSQL service; locally we fall back to SQLite.
TEST_DB = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")


def _reset(db):
    if db.kind == "postgres":
        db.execute("TRUNCATE staged_records, import_jobs RESTART IDENTITY CASCADE")


@pytest.fixture
def sf():
    return MockSalesforce()


@pytest.fixture
def app(sf):
    app = create_app({"DATABASE_URL": TEST_DB, "SALESFORCE": sf, "TESTING": True})
    _reset(app.extensions["db"])
    yield app
    _reset(app.extensions["db"])


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    return app.extensions["db"]
