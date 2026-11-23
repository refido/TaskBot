"""Opt-in PostgreSQL checks against a disposable database on the local test cluster."""

import os
from contextlib import closing
from datetime import datetime, timedelta
from uuid import uuid4

import psycopg2
import pytest

from src.infrastructure.database.operator_store import (
    DatabaseConfig,
    OperatorDatabaseManager,
    OperatorTarget,
    OperatorTargets,
)


@pytest.fixture
def pg_delivery():
    database = os.getenv("TASKBOT_QUOTA_TEST_DB")
    if not database:
        pytest.skip("Set TASKBOT_QUOTA_TEST_DB to opt in to the isolated PostgreSQL tests")
    if not database.startswith("taskbot_quota_test_"):
        pytest.fail("Expected a disposable taskbot_quota_test_ database")
    with closing(psycopg2.connect(host="127.0.0.1", port=55432, dbname=database, connect_timeout=3)) as conn:
        with conn, conn.cursor() as cursor:
            cursor.execute("SELECT current_setting('cluster_name'), current_database()")
            assert cursor.fetchone() == ("taskbot_phase1", database)
            cursor.execute(OperatorDatabaseManager._create_table_sql("OPERATOR_1"))
        manager = OperatorDatabaseManager(
            DatabaseConfig("127.0.0.1", 55432, database, "fixture", ""),
            OperatorTargets((OperatorTarget("OPERATOR_1", "Fixture", operator_id="operator_01"),)),
        )
        manager.ensure_delivery_receipts(conn)
        yield conn, manager


def record(pg_delivery, event, nik, when):
    conn, manager = pg_delivery
    manager.sync_report_payloads(
        [{"nik": nik, "operator_id": "operator_01", "status": "completed", "finished_at": when.isoformat()}],
        source="dummy-report", connection=conn, delivery_id=event,
    )


def stored(pg_delivery, nik):
    conn, _ = pg_delivery
    with conn, conn.cursor() as cursor:
        cursor.execute('SELECT "KUOTA", "MAX_KUOTA" FROM public."OPERATOR_1" WHERE "NIK"=%s', (nik,))
        quota = cursor.fetchone()
        cursor.execute("SELECT count(*) FROM public.taskbot_quota_receipts WHERE nik=%s", (nik,))
        return quota, cursor.fetchone()[0]


def test_receipt_and_increment_roll_back_together(pg_delivery, monkeypatch):
    _, manager = pg_delivery
    nik = uuid4().int % 10**13
    event, when = str(uuid4()), datetime.now().astimezone()
    upsert = manager.upsert_record

    def interrupt(*args, **kwargs):
        upsert(*args, **kwargs)
        raise RuntimeError("interrupted before commit")

    with monkeypatch.context() as patch:
        patch.setattr(manager, "upsert_record", interrupt)
        with pytest.raises(RuntimeError, match="before commit"):
            record(pg_delivery, event, nik, when)
    assert stored(pg_delivery, nik) == (None, 0)
    record(pg_delivery, event, nik, when)
    record(pg_delivery, event, nik, when)
    assert stored(pg_delivery, nik) == ((1, 1), 1)


def test_distinct_receipts_at_equal_and_earlier_times_count_once(pg_delivery):
    nik = uuid4().int % 10**13
    when = datetime.now().astimezone().replace(day=2, hour=12)
    for stamp in (when, when, when - timedelta(days=1)):
        event = str(uuid4())
        record(pg_delivery, event, nik, stamp)
        record(pg_delivery, event, nik, stamp)
    assert stored(pg_delivery, nik) == ((3, 3), 3)
    with pytest.raises(ValueError, match="does not match"):
        record(pg_delivery, event, nik, when + timedelta(seconds=1))
    assert stored(pg_delivery, nik) == ((3, 3), 3)


def test_recovered_prior_month_sale_does_not_consume_this_months_quota(pg_delivery):
    nik = uuid4().int % 10**13
    when = datetime.now().astimezone()
    previous = when.replace(day=1) - timedelta(days=1)
    record(pg_delivery, str(uuid4()), nik, previous)
    assert stored(pg_delivery, nik) == ((0, 1), 1)
    record(pg_delivery, str(uuid4()), nik, when)
    record(pg_delivery, str(uuid4()), nik, previous)
    assert stored(pg_delivery, nik) == ((1, 1), 3)


def test_unlogged_table_cannot_acknowledge_quota(pg_delivery):
    conn, manager = pg_delivery
    with conn, conn.cursor() as cursor:
        cursor.execute('CREATE UNLOGGED TABLE IF NOT EXISTS public."OPERATOR_99" (id bigint)')
    targets = OperatorTargets((OperatorTarget("OPERATOR_99", "Fixture", operator_id="operator_99"),))
    with pytest.raises(RuntimeError, match="permanent logged table"):
        OperatorDatabaseManager(manager.config, targets).ensure_delivery_receipts(conn)


def test_legacy_report_reimport_keeps_the_already_delivered_quota(pg_delivery):
    conn, manager = pg_delivery
    nik = uuid4().int % 10**13
    when = datetime.now().astimezone()
    record(pg_delivery, str(uuid4()), nik, when)
    manager.sync_report_payloads(
        [{"nik": nik, "operator_id": "operator_01", "status": "completed", "finished_at": when.isoformat()}],
        source="dummy-items.jsonl", connection=conn,
    )
    assert stored(pg_delivery, nik) == ((1, 1), 1)
