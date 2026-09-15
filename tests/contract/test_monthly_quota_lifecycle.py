"""Temporary quota-reset ownership, independent of connection destruction/GC.

The transaction double models psycopg2 2.9.12: __exit__ commits or rolls back,
but never closes. Real manager SQL and the real setup orchestration are used.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main as taskbot_main
from src.infrastructure.database import operator_store


@pytest.mark.parametrize("primary_type", [None, RuntimeError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("log_stage", ["bind", "exception"])
def test_cleanup_logging_failure_preserves_operation(quota_case, primary_type, log_stage):
    case = quota_case
    primary = primary_type("operation failed") if primary_type else None
    if primary:
        case.errors["sql"] = primary
    case.errors["connection.close"] = OSError("close failed")
    log_error = RuntimeError("cleanup logger failed")

    def bind(**context):
        if context.get("event") == "database.monthly_quota_reset.connection.close_failed":
            if log_stage == "bind":
                raise log_error
            return Mock(exception=Mock(side_effect=log_error))
        return Mock()

    case.log.bind.side_effect = bind
    if primary:
        with pytest.raises(type(primary)) as caught:
            case.manager.reset_monthly_quotas()
        assert caught.value is primary
    else:
        assert case.manager.reset_monthly_quotas() is None
    case.connections[0].close.assert_called_once_with()


@pytest.fixture
def quota_case(monkeypatch):
    case = SimpleNamespace(
        connections=[], events=[], errors={}, rowcount=3,
        reference_time=datetime(2026, 6, 1),
    )

    def step(name):
        case.events.append(name)
        if name in case.errors:
            raise case.errors[name]

    class Cursor:
        def __init__(self, connection):
            self.connection = connection
            self.closed = False
            self.statements = []
            self.rowcount = case.rowcount

        def __enter__(self):
            step("cursor.enter")
            return self

        def __exit__(self, *_args):
            self.closed = True
            step("cursor.close")
            return False

        def execute(self, statement, params=None):
            step("sql")
            if self.statements:
                step("next.sql")
            self.statements.append((statement, params))
            self.connection.pending.append(statement)

        def fetchone(self):
            return (1,)  # Maintenance database existence check.

        def fetchall(self):
            return [(name,) for name in operator_store._COLUMN_NAMES]

    class Connection:
        def __init__(self, database):
            self.database = database
            self.closed = False
            self.pending, self.committed = [], []
            self.cursor_instance = None
            self.commit = Mock(side_effect=self.do_commit)
            self.rollback = Mock(side_effect=self.do_rollback)
            self.close = Mock(side_effect=self.do_close)

        def __enter__(self):
            step("transaction.enter")
            return self

        def __exit__(self, exc_type, *_args):
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
            return False

        def cursor(self):
            step("cursor.open")
            self.cursor_instance = Cursor(self)
            return self.cursor_instance

        def do_commit(self):
            step("commit")
            self.committed.extend(self.pending)
            self.pending.clear()

        def do_rollback(self):
            step("rollback")
            self.pending.clear()

        def do_close(self):
            step("connection.close")
            self.closed = True

    def connect(**kwargs):
        step("open")
        connection = Connection(kwargs["dbname"])
        case.connections.append(connection)
        return connection

    case.connect = Mock(side_effect=connect)
    monkeypatch.setattr(operator_store.psycopg2, "connect", case.connect)
    case.log = Mock()
    monkeypatch.setattr(operator_store, "logger", case.log)
    case.manager = operator_store.OperatorDatabaseManager(
        operator_store.DatabaseConfig(
            host="localhost", port=5432, name="taskbot", user="taskbot", password="test",
        ),
    )
    return case


def assert_reset_released(connection):
    connection.close.assert_called_once_with()
    assert connection.closed


@pytest.mark.parametrize("rowcount", [3, 0, None], ids=["updated", "no-rows", "unknown-count"])
def test_reset_success_transaction_query_and_resource_lifecycle(quota_case, rowcount):
    case = quota_case
    case.rowcount = rowcount
    assert case.manager.reset_monthly_quotas(case.reference_time) is None
    case.connect.assert_called_once_with(
        host="localhost", port=5432, dbname="taskbot", user="taskbot", password="test",
    )
    connection, = case.connections
    connection.commit.assert_called_once_with()
    connection.rollback.assert_not_called()
    assert connection.cursor_instance.closed
    assert case.events[:3] == ["open", "transaction.enter", "cursor.open"]
    assert case.events.index("cursor.close") < case.events.index("commit")
    assert connection.pending == []
    assert len(connection.committed) == 2
    for table, (statement, params) in zip(
        ("OPERATOR_1", "OPERATOR_2"), connection.cursor_instance.statements, strict=True,
    ):
        assert params == (case.reference_time,)
        # Compare the full composable query, including predicates and columns.
        expected = operator_store.sql.SQL(
            """
                        UPDATE {table}
                        SET {kuota} = 0
                        WHERE date_trunc('month', {updated_time})
                              < date_trunc('month', %s::timestamp)
                          AND {kuota} <> 0
                        """
        ).format(
            table=operator_store.sql.Identifier(table),
            kuota=operator_store.sql.Identifier("KUOTA"),
            updated_time=operator_store.sql.Identifier("UPDATED_TIME"),
        )
        assert statement == expected
    finished = [
        call.kwargs for call in case.log.bind.call_args_list
        if call.kwargs.get("event") == "database.monthly_quota_reset.finished"
    ]
    assert len(finished) == 1
    assert finished[0]["row_counts"] == {"OPERATOR_1": rowcount, "OPERATOR_2": rowcount}
    assert_reset_released(connection)
    assert case.events[-2:] == ["commit", "connection.close"]
    assert not any(
        call.kwargs.get("event") == "database.monthly_quota_reset.connection.close_failed"
        for call in case.log.bind.call_args_list
    )


@pytest.mark.parametrize("stage", [
    "transaction.enter", "cursor.open", "cursor.enter", "sql", "next.sql", "cursor.close", "commit",
])
def test_reset_failure_preserves_exception_and_transaction_behavior(quota_case, stage):
    case = quota_case
    error = RuntimeError(stage)
    case.errors[stage] = error
    with pytest.raises(RuntimeError) as caught:
        case.manager.reset_monthly_quotas(case.reference_time)
    assert caught.value is error
    connection, = case.connections
    assert connection.commit.call_count == int(stage == "commit")
    assert connection.rollback.call_count == int(stage not in ("transaction.enter", "commit"))
    assert connection.committed == []
    if stage == "next.sql":
        assert len(connection.cursor_instance.statements) == 1
        assert connection.pending == []  # First table is rolled back too.
    assert_reset_released(connection)
    assert case.events[-1] == "connection.close"


def test_reset_connect_failure_has_no_owned_resource(quota_case):
    case = quota_case
    error = RuntimeError("connect failed")
    case.errors["open"] = error
    with pytest.raises(RuntimeError) as caught:
        case.manager.reset_monthly_quotas(case.reference_time)
    assert caught.value is error
    assert case.connections == []
    assert case.events == ["open"]


def test_repeated_reset_owns_distinct_connections(quota_case):
    case = quota_case
    for _ in range(3):
        case.manager.reset_monthly_quotas(case.reference_time)
    assert len(case.connections) == 3
    assert len({id(connection) for connection in case.connections}) == 3
    for connection in case.connections:
        connection.commit.assert_called_once_with()
        assert_reset_released(connection)


def test_reset_rollback_failure_keeps_existing_driver_precedence(quota_case):
    case = quota_case
    sql_error, rollback_error = ValueError("SQL failed"), RuntimeError("rollback failed")
    case.errors.update(sql=sql_error, rollback=rollback_error)
    with pytest.raises(RuntimeError) as caught:
        case.manager.reset_monthly_quotas(case.reference_time)
    assert caught.value is rollback_error
    assert caught.value.__context__ is sql_error
    connection, = case.connections
    connection.rollback.assert_called_once_with()
    connection.commit.assert_not_called()
    assert_reset_released(connection)


@pytest.mark.parametrize("stage", [None, "sql", "next.sql", "commit", "rollback"])
@pytest.mark.parametrize("close_type", [RuntimeError, KeyboardInterrupt])
def test_reset_close_failure_precedence_and_logging(quota_case, stage, close_type):
    case = quota_case
    primary = RuntimeError("reset failed") if stage else None
    close_error = close_type("close failed")
    case.errors["connection.close"] = close_error
    if stage:
        case.errors[stage] = primary
        if stage == "rollback":
            case.errors["sql"] = ValueError("SQL failed before rollback")
    expected = primary or (close_error if close_type is KeyboardInterrupt else None)
    if expected:
        with pytest.raises(type(expected)) as caught:
            case.manager.reset_monthly_quotas(case.reference_time)
        assert caught.value is expected
    else:
        assert case.manager.reset_monthly_quotas(case.reference_time) is None
    connection, = case.connections
    connection.close.assert_called_once_with()
    assert not connection.closed
    assert case.events[-1] == "connection.close"
    if stage is None:
        assert len(connection.committed) == 2
    if stage or close_type is RuntimeError:
        assert any(
            call.kwargs.get("event") == "database.monthly_quota_reset.connection.close_failed"
            for call in case.log.bind.call_args_list
        )
        case.log.bind.return_value.exception.assert_called_once()


def test_reset_interrupt_still_rolls_back_and_closes(quota_case):
    case = quota_case
    error = KeyboardInterrupt("reset interrupted")
    case.errors["next.sql"] = error
    with pytest.raises(KeyboardInterrupt) as caught:
        case.manager.reset_monthly_quotas(case.reference_time)
    assert caught.value is error
    connection, = case.connections
    connection.rollback.assert_called_once_with()
    assert connection.pending == connection.committed == []
    assert_reset_released(connection)


def test_reset_failure_then_success_releases_each_connection(quota_case):
    case = quota_case
    case.errors["next.sql"] = RuntimeError("first reset failed")
    with pytest.raises(RuntimeError):
        case.manager.reset_monthly_quotas(case.reference_time)
    case.errors.clear()
    case.manager.reset_monthly_quotas(case.reference_time)
    assert len(case.connections) == 2
    case.connections[0].rollback.assert_called_once_with()
    case.connections[1].commit.assert_called_once_with()
    for connection in case.connections:
        assert_reset_released(connection)


def test_full_setup_owns_three_temporary_connections_separate_from_syncer(quota_case):
    case = quota_case
    syncer = taskbot_main.DatabaseReportSyncer()
    syncer._ensure_database(case.manager)
    assert len(case.connections) == 3
    maintenance, tables, quotas = case.connections
    assert [connection.database for connection in case.connections] == [
        case.manager.config.maintenance_name, "taskbot", "taskbot",
    ]
    assert maintenance.autocommit is True
    maintenance.commit.assert_not_called()
    tables.commit.assert_called_once_with()
    quotas.commit.assert_called_once_with()
    for connection in case.connections:
        assert connection.cursor_instance.closed
        assert_reset_released(connection)
    # Every owner releases its connection before the next owner acquires one.
    opens = [i for i, event in enumerate(case.events) if event == "open"]
    closes = [i for i, event in enumerate(case.events) if event == "connection.close"]
    assert opens[0] < closes[0] < opens[1] < closes[1] < opens[2] < closes[2]

    persistent = syncer._get_connection(case.manager)
    case.manager.reset_monthly_quotas(case.reference_time)
    assert len(case.connections) == 5
    assert_reset_released(case.connections[-1])
    persistent.close.assert_not_called()
    assert not persistent.closed
    syncer._ensure_database(case.manager)
    assert syncer._get_connection(case.manager) is persistent
    assert len(case.connections) == 5
    syncer.close()
    syncer.close()
    assert_reset_released(persistent)
    for connection in case.connections:
        connection.close.assert_called_once_with()
