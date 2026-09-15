"""Setup owns temporary connections; psycopg2 contexts own transactions only.

Keep every connection strongly referenced, independently of GC. The double models
psycopg2 2.9.12 __exit__: commit on success, rollback on error, never close.
Real table creation/migration SQL is exercised without a PostgreSQL server.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main as taskbot_main
from src.infrastructure.database import operator_store


@pytest.mark.parametrize("primary_type", [None, RuntimeError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("log_stage", ["bind", "exception"])
def test_cleanup_logging_failure_preserves_operation(setup_case, primary_type, log_stage):
    case = setup_case
    primary = primary_type("operation failed") if primary_type else None
    if primary:
        case.errors["sql"] = primary
    case.errors["connection.close"] = OSError("close failed")
    log_error = RuntimeError("cleanup logger failed")

    def bind(**context):
        if context.get("event") == "database.tables.connection.close_failed":
            if log_stage == "bind":
                raise log_error
            return Mock(exception=Mock(side_effect=log_error))
        return Mock()

    case.log.bind.side_effect = bind
    if primary:
        with pytest.raises(type(primary)) as caught:
            case.manager.ensure_tables_exist()
        assert caught.value is primary
    else:
        assert case.manager.ensure_tables_exist() is None
    case.connections[0].close.assert_called_once_with()


@pytest.fixture
def setup_case(monkeypatch):
    case = SimpleNamespace(
        connections=[], events=[], errors={}, existing=False,
    )

    def step(name):
        case.events.append(name)
        if name in case.errors:
            raise case.errors[name]

    class Cursor:
        def __init__(self):
            self.closed = False
            self.statements = []

        def __enter__(self):
            step("cursor.enter")
            return self

        def __exit__(self, *_args):
            self.closed = True
            step("cursor.close")
            return False

        def execute(self, statement, params=None):
            step("sql")
            self.statements.append((statement, params))

        def fetchall(self):
            step("fetch")
            return [(name,) for name in operator_store._COLUMN_NAMES] if case.existing else []

    class Connection:
        def __init__(self):
            self.closed = False
            self.cursor_instance = None
            self.commit = Mock(side_effect=lambda: step("commit"))
            self.rollback = Mock(side_effect=lambda: step("rollback"))
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
            self.cursor_instance = Cursor()
            return self.cursor_instance

        def do_close(self):
            step("connection.close")
            self.closed = True

    def connect(**_kwargs):
        step("open")
        connection = Connection()
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


def assert_setup_connection_released(connection):
    connection.close.assert_called_once_with()
    assert connection.closed


@pytest.mark.parametrize("existing", [False, True], ids=["new-tables", "existing-tables"])
def test_setup_success_transaction_and_resource_lifecycle(setup_case, existing):
    case = setup_case
    case.existing = existing
    assert case.manager.ensure_tables_exist() is None
    case.connect.assert_called_once_with(
        host="localhost", port=5432, dbname="taskbot", user="taskbot", password="test",
    )
    connection, = case.connections
    connection.commit.assert_called_once_with()
    connection.rollback.assert_not_called()
    assert connection.cursor_instance.closed
    assert case.events.index("cursor.close") < case.events.index("commit")
    statements = connection.cursor_instance.statements
    assert sum("CREATE TABLE IF NOT EXISTS" in str(sql) for sql, _ in statements) == 2
    assert [params for _, params in statements if params] == [("OPERATOR_1",), ("OPERATOR_2",)]
    assert_setup_connection_released(connection)
    assert case.events[-2:] == ["commit", "connection.close"]
    assert not any(
        call.kwargs.get("event") == "database.tables.connection.close_failed"
        for call in case.log.bind.call_args_list
    )


@pytest.mark.parametrize("stage", [
    "transaction.enter", "cursor.open", "cursor.enter", "sql", "fetch", "cursor.close", "commit",
])
def test_setup_failure_preserves_error_and_transaction_behavior(setup_case, stage):
    case = setup_case
    error = RuntimeError(stage)
    case.errors[stage] = error
    with pytest.raises(RuntimeError) as caught:
        case.manager.ensure_tables_exist()
    assert caught.value is error
    connection, = case.connections
    assert connection.commit.call_count == int(stage == "commit")
    assert connection.rollback.call_count == int(stage not in ("transaction.enter", "commit"))
    if stage in ("sql", "fetch", "cursor.close", "commit"):
        assert connection.cursor_instance.closed
    assert_setup_connection_released(connection)
    assert case.events[-1] == "connection.close"


def test_setup_connect_failure_has_no_owned_resource(setup_case):
    case = setup_case
    error = RuntimeError("connect failed")
    case.errors["open"] = error
    with pytest.raises(RuntimeError) as caught:
        case.manager.ensure_tables_exist()
    assert caught.value is error
    assert case.connections == []
    assert case.events == ["open"]


def test_manager_and_syncer_constructors_do_not_connect(setup_case):
    taskbot_main.DatabaseReportSyncer()
    setup_case.connect.assert_not_called()


def test_repeated_setup_owns_distinct_connections(setup_case):
    case = setup_case
    for _ in range(3):
        case.manager.ensure_tables_exist()
    assert len(case.connections) == 3
    assert len({id(connection) for connection in case.connections}) == 3
    for connection in case.connections:
        connection.commit.assert_called_once_with()
        assert_setup_connection_released(connection)


def test_rollback_failure_keeps_existing_psycopg2_exception_semantics(setup_case):
    case = setup_case
    sql_error, rollback_error = RuntimeError("SQL failed"), RuntimeError("rollback failed")
    case.errors.update(sql=sql_error, rollback=rollback_error)
    with pytest.raises(RuntimeError) as caught:
        case.manager.ensure_tables_exist()
    assert caught.value is rollback_error
    assert caught.value.__context__ is sql_error
    connection, = case.connections
    connection.rollback.assert_called_once_with()
    connection.commit.assert_not_called()
    assert_setup_connection_released(connection)


@pytest.mark.parametrize("stage", [None, "sql", "fetch", "commit", "rollback"])
@pytest.mark.parametrize("close_type", [RuntimeError, KeyboardInterrupt])
def test_close_failure_precedence_and_observability(setup_case, stage, close_type):
    case = setup_case
    primary = RuntimeError("primary setup failure") if stage else None
    close_error = close_type("close failed")
    case.errors["connection.close"] = close_error
    if stage:
        case.errors[stage] = primary
        if stage == "rollback":
            case.errors["sql"] = ValueError("SQL failed before rollback")
    expected = primary or (close_error if close_type is KeyboardInterrupt else None)
    if expected:
        with pytest.raises(type(expected)) as caught:
            case.manager.ensure_tables_exist()
        assert caught.value is expected
    else:
        assert case.manager.ensure_tables_exist() is None
    connection, = case.connections
    connection.close.assert_called_once_with()
    assert not connection.closed  # A failed close cannot guarantee release.
    assert case.events[-1] == "connection.close"
    if stage or close_type is RuntimeError:
        assert any(
            call.kwargs.get("event") == "database.tables.connection.close_failed"
            for call in case.log.bind.call_args_list
        )
        case.log.bind.return_value.exception.assert_called_once()


def test_interrupted_setup_still_closes_and_preserves_primary(setup_case):
    case = setup_case
    error = KeyboardInterrupt("setup interrupted")
    case.errors["sql"] = error
    with pytest.raises(KeyboardInterrupt) as caught:
        case.manager.ensure_tables_exist()
    assert caught.value is error
    connection, = case.connections
    connection.rollback.assert_called_once_with()
    assert_setup_connection_released(connection)


def test_setup_failure_then_success_each_releases_own_connection(setup_case):
    case = setup_case
    case.errors["sql"] = RuntimeError("first setup failed")
    with pytest.raises(RuntimeError):
        case.manager.ensure_tables_exist()
    case.errors.clear()
    case.manager.ensure_tables_exist()
    assert len(case.connections) == 2
    case.connections[0].rollback.assert_called_once_with()
    case.connections[1].commit.assert_called_once_with()
    for connection in case.connections:
        assert_setup_connection_released(connection)


def test_setup_and_persistent_syncer_own_separate_connections(setup_case):
    case = setup_case
    # Isolate the table setup stage; database creation/quota reset are separate
    # owners and are deliberately outside this lifecycle change.
    case.manager.ensure_database_exists = Mock()
    case.manager.reset_monthly_quotas = Mock()
    syncer = taskbot_main.DatabaseReportSyncer()
    syncer._ensure_database(case.manager)
    temporary, = case.connections
    assert_setup_connection_released(temporary)
    persistent = syncer._get_connection(case.manager)
    assert persistent is not temporary
    assert not persistent.closed
    persistent.close.assert_not_called()
    syncer._ensure_database(case.manager)
    assert syncer._get_connection(case.manager) is persistent
    assert len(case.connections) == 2
    # Even a direct repeated setup must not touch the existing persistent owner.
    case.manager.ensure_tables_exist()
    assert_setup_connection_released(case.connections[2])
    persistent.close.assert_not_called()
    syncer.close()
    syncer.close()
    assert_setup_connection_released(persistent)
    temporary.close.assert_called_once_with()
