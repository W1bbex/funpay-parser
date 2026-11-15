from __future__ import annotations

import os

# Set immediately on pytest startup to ensure hermetic logging during collection
os.environ["PYTEST_CURRENT_TEST"] = "1"

import pytest


@pytest.fixture(autouse=True)
def hermetic_fs(tmp_path_factory, monkeypatch):
    """Hermetic filesystem sandbox for all tests.

    Ensures that test execution does not touch production data/, logs/,
    or analytics.sqlite3 databases, while keeping test-specific tmp_path clean.
    """
    sandbox = tmp_path_factory.mktemp("hermetic_sandbox")
    data_dir = sandbox / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_file = sandbox / "analytics.sqlite3"

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    monkeypatch.setenv("FUNPAY_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FUNPAY_DB_PATH", str(db_file))

    yield sandbox
