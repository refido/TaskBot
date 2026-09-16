"""Owned payload-sync cleanup, independent of PostgreSQL and GC timing."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.infrastructure.database import operator_store


@pytest.mark.parametrize("primary_type", [None, RuntimeError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("log_stage", ["bind", "exception"])
def test_cleanup_logging_failure_preserves_sync_result(case, primary_type, log_stage):
    primary = primary_type("sync failed") if primary_type else None
    if primary:
        case.errors["body"] = primary
    case.errors["close"] = OSError("close failed")
    log_error = RuntimeError("cleanup logger failed")
    bound = Mock()

    def bind(**context):
        if context.get("event") == "database.report_sync.connection.close_failed":
            if log_stage == "bind":
                raise log_error
            return Mock(exception=Mock(side_effect=log_error))
        return bound

    case.log.bind.side_effect = bind
    if primary:
        with pytest.raises(type(primary)) as caught:
            case.run()
        assert caught.value is primary
    else:
        assert case.run().processed == 2
    case.connections[0].close.assert_called_once_with()


@pytest.mark.parametrize("fatal_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("primary", [False, True])
def test_fatal_cleanup_logger_interruption_still_propagates(case, fatal_type, primary):
    interruption = fatal_type("logging interrupted")
    if primary:
        case.errors["body"] = RuntimeError("sync failed")
    case.errors["close"] = OSError("close failed")

    def bind(**context):
        if context.get("event") == "database.report_sync.connection.close_failed":
            raise interruption
        return Mock()

    case.log.bind.side_effect = bind
    with pytest.raises(fatal_type) as caught:
        case.run()
    assert caught.value is interruption
    case.connections[0].close.assert_called_once_with()


@pytest.fixture
def case(monkeypatch):
    case = SimpleNamespace(events=[], errors={}, connections=[], calls=0)

    def step(name):
        case.events.append(name)
        if name in case.errors:
            raise case.errors[name]

    class Cursor:
        def __init__(self):
            self.closed = False

        def __enter__(self):
            step("cursor.enter")
            return self

        def __exit__(self, *_args):
            step("cursor.close")
            self.closed = True
            return False

    class Connection:
        def __init__(self):
            self.closed = False
            self.cursor_instance = Cursor()
            self.pending, self.committed = [], []
            self.close = Mock(side_effect=self.do_close)
            self.commit = Mock(side_effect=self.do_commit)
            self.rollback = Mock(side_effect=self.do_rollback)

        def __enter__(self):
            step("transaction.enter")
            return self

        def __exit__(self, exc_type, *_args):
            # psycopg2 transaction context commits/rolls back; it never closes.
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
            return False

        def cursor(self):
            step("cursor.open")
            return self.cursor_instance

        def do_commit(self):
            step("commit")
            self.committed.extend(self.pending)
            self.pending.clear()

        def do_rollback(self):
            step("rollback")
            self.pending.clear()

        def do_close(self):
            step("close")
            self.closed = True

    def connect(database):
        assert database == "taskbot"
        step("connect")
        connection = Connection()
        case.connections.append(connection)
        return connection

    case.manager = operator_store.OperatorDatabaseManager(
        operator_store.DatabaseConfig(
            host="localhost",
            port=5432,
            name="taskbot",
            user="taskbot",
            password="test",
        )
    )
    case.connect = Mock(side_effect=connect)
    monkeypatch.setattr(case.manager, "_connect", case.connect)
    case.log = Mock()
    monkeypatch.setattr(operator_store, "logger", case.log)

    def upsert(payload, *, cursor, table_name):
        assert table_name == "OPERATOR_1"
        assert cursor is case.active.cursor_instance
        case.calls += 1
        step("body" if case.calls % 2 else "second.body")
        case.active.pending.append(payload)

    monkeypatch.setattr(case.manager, "upsert_report_payload", upsert)
    case.Connection = Connection
    case.payloads = [
        {"nik": "1", "status": "completed"},
        {"nik": "2", "status": "error"},
    ]

    def run(connection=None, payloads=None):
        # Resolve active connection only as the transaction body executes.
        original = case.manager.upsert_report_payload

        def use_active(*args, **kwargs):
            case.active = connection if connection is not None else case.connections[-1]
            return original(*args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(case.manager, "upsert_report_payload", use_active)
            return case.manager.sync_report_payloads(
                case.payloads if payloads is None else payloads,
                source="batch",
                table_name="OPERATOR_1",
                connection=connection,
            )

    case.run = run
    return case


@pytest.mark.parametrize("supplied", [False, True])
@pytest.mark.parametrize("empty", [False, True])
def test_success_transaction_and_ownership(case, supplied, empty):
    connection = case.Connection() if supplied else None
    summary = case.run(connection, payloads=[] if empty else case.payloads)
    connection = connection if supplied else case.connections[0]
    assert (
        summary.source,
        summary.processed,
        summary.inserted_or_updated,
        summary.skipped,
    ) == ("batch", 0 if empty else 2, 0 if empty else 2, 0)
    connection.commit.assert_called_once_with()
    connection.rollback.assert_not_called()
    assert connection.cursor_instance.closed
    assert connection.committed == ([] if empty else case.payloads)
    assert connection.close.call_count == (0 if supplied else 1)
    assert connection.closed is not supplied
    assert case.connect.call_count == (0 if supplied else 1)
    assert case.events[-2:] == (
        ["cursor.close", "commit"] if supplied else ["commit", "close"]
    )


@pytest.mark.parametrize("supplied", [False, True])
@pytest.mark.parametrize(
    "stage",
    [
        "transaction.enter",
        "cursor.open",
        "cursor.enter",
        "body",
        "second.body",
        "cursor.close",
        "commit",
        "rollback",
    ],
)
def test_primary_error_without_close_failure(case, supplied, stage):
    primary = RuntimeError(stage)
    case.errors[stage] = primary
    if stage == "rollback":
        case.errors["body"] = RuntimeError("body before rollback")
    connection = case.Connection() if supplied else None
    with pytest.raises(RuntimeError) as caught:
        case.run(connection)
    assert caught.value is primary
    connection = connection if supplied else case.connections[0]
    assert connection.close.call_count == (0 if supplied else 1)
    assert connection.closed is not supplied
    assert connection.rollback.call_count == (
        stage not in {"transaction.enter", "commit"}
    )
    if stage in {"body", "second.body"}:
        assert connection.pending == connection.committed == []
    if stage == "rollback":
        assert primary.__context__ is case.errors["body"]


def test_connect_failure_does_not_close_nonexistent_resource(case):
    primary = RuntimeError("connect")
    case.errors["connect"] = primary
    with pytest.raises(RuntimeError) as caught:
        case.run()
    assert caught.value is primary
    assert case.connections == []
    assert case.events == ["connect"]


@pytest.mark.parametrize("stage", [None, "body", "second.body", "commit", "rollback"])
@pytest.mark.parametrize("close_type", [RuntimeError, KeyboardInterrupt])
def test_owned_close_failure_precedence(case, stage, close_type):
    primary = RuntimeError("primary " + stage) if stage else None
    close_error = close_type("close failed")
    case.errors["close"] = close_error
    if stage:
        case.errors[stage] = primary
        if stage == "rollback":
            case.errors["body"] = RuntimeError("body before rollback")
    # Setup/reset policy: preserve primary; ordinary cleanup is best-effort.
    expected = primary or (close_error if close_type is KeyboardInterrupt else None)
    if expected:
        with pytest.raises(BaseException) as caught:
            case.run()
        assert caught.value is expected
    else:
        assert case.run().processed == 2
    (connection,) = case.connections
    connection.close.assert_called_once_with()
    assert not connection.closed
    assert case.events[-1] == "close"
    logged = [
        call
        for call in case.log.bind.call_args_list
        if call.kwargs.get("event") == "database.report_sync.connection.close_failed"
    ]
    assert len(logged) == int(primary is not None or close_type is RuntimeError)


@pytest.mark.parametrize("stage", [None, "body", "commit", "rollback"])
def test_supplied_connection_does_not_attempt_failing_close(case, stage):
    connection = case.Connection()
    case.errors["close"] = RuntimeError("caller owns cleanup")
    if stage:
        case.errors[stage] = RuntimeError(stage)
        if stage == "rollback":
            case.errors["body"] = RuntimeError("body")
        with pytest.raises(RuntimeError) as caught:
            case.run(connection)
        assert caught.value is case.errors[stage]
    else:
        assert case.run(connection).processed == 2
    connection.close.assert_not_called()
    case.connect.assert_not_called()


def test_repeated_owned_calls_close_distinct_connections(case):
    for _ in range(3):
        assert case.run().processed == 2
    assert len({id(c) for c in case.connections}) == 3
    for connection in case.connections:
        connection.close.assert_called_once_with()
        connection.commit.assert_called_once_with()


def test_value_error_row_skip_keeps_commit_contract(case):
    case.errors["body"] = ValueError("invalid payload")
    summary = case.run()
    assert (summary.processed, summary.inserted_or_updated, summary.skipped) == (
        2,
        1,
        1,
    )
    assert case.connections[0].committed == [case.payloads[1]]


@pytest.mark.parametrize("primary_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("close_type", [RuntimeError, KeyboardInterrupt])
def test_fatal_primary_still_rolls_back_and_remains_primary(
    case, primary_type, close_type
):
    primary = primary_type("sync interrupted")
    case.errors.update({"second.body": primary, "close": close_type("close failed")})
    with pytest.raises(BaseException) as caught:
        case.run()
    assert caught.value is primary
    (connection,) = case.connections
    connection.rollback.assert_called_once_with()
    connection.commit.assert_not_called()
    connection.close.assert_called_once_with()
    assert connection.pending == connection.committed == []
    assert any(
        call.kwargs.get("event") == "database.report_sync.connection.close_failed"
        for call in case.log.bind.call_args_list
    )
