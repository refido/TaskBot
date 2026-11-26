"""Replay the DB1 paper examples in pytest on SQLite and the opt-in test cluster."""

import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import psycopg2
import pytest

EXAMPLE = (
    Path(__file__).resolve().parents[2] / "db_query/db1-customer-queue-example.sql"
)
EXPECTED_QUEUES = {
    "same day": "CEF",
    "ordinary": "CABEF",
    "month start": "CABDEF",
    "later in the month": "CABEFD",
    "restart after C": "ABDEF",
    "outside eligible": "G",
}


def _assert_queues(rows: list[tuple[str, str]]) -> None:
    queues: dict[str, list[str]] = {}
    for scenario, label in rows:
        queues.setdefault(scenario, []).append(label)
    assert queues == {
        scenario: list(labels) for scenario, labels in EXPECTED_QUEUES.items()
    }


def test_sqlite_customer_queues() -> None:
    """Check each fictional queue in a fresh in-memory database during pytest."""
    with closing(sqlite3.connect(":memory:")) as connection:
        _assert_queues(
            connection.execute(EXAMPLE.read_text(encoding="utf-8")).fetchall()
        )


def test_postgres_customer_queues() -> None:
    """Check the same SQL and expected queues in a read-only PostgreSQL test session."""
    database = os.getenv("TASKBOT_QUOTA_TEST_DB")
    if not database:
        pytest.skip("Set TASKBOT_QUOTA_TEST_DB to run the local PostgreSQL example")
    if not re.fullmatch(r"taskbot_quota_test_[a-zA-Z0-9_]+", database):
        pytest.fail("Expected a disposable taskbot_quota_test_ database")
    with (
        closing(
            psycopg2.connect(
                host="127.0.0.1",
                port=55432,
                dbname=database,
                connect_timeout=3,
                options="-c default_transaction_read_only=on",
            )
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT current_setting('cluster_name'), current_database(), "
            "current_setting('transaction_read_only')"
        )
        assert cursor.fetchone() == ("taskbot_phase1", database, "on")
        cursor.execute(EXAMPLE.read_text(encoding="utf-8"))
        _assert_queues(cursor.fetchall())
