"""One-off ownership tests using the real syncer and manager transaction path.

Connections remain strongly referenced by the test: no assertion relies on GC.
The fake DB transaction models commit/rollback; no PostgreSQL server is needed.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

import main as taskbot_main
from src.infrastructure.database.operator_store import OperatorDatabaseManager
from src.web.reporter import TransactionRow


@pytest.fixture
def db_case(monkeypatch, tmp_path):
    events, connections, instances, committed = [], [], [], []
    case = SimpleNamespace(events=events, connections=connections, instances=instances,
                           committed=committed, fail_nik=None, skip_nik=None,
                           close_error=None)

    class Connection:
        def __init__(self):
            self.closed = False
            self.pending = []
            self.close = Mock(side_effect=self.do_close)

        def __enter__(self):
            events.append("begin")
            return self

        def __exit__(self, exc_type, exc, tb):
            events.append("rollback" if exc_type else "commit")
            if exc_type is None:
                committed.extend(self.pending)
            self.pending.clear()
            return False

        def cursor(self):
            return MagicMock()

        def do_close(self):
            events.append("connection.close")
            if case.close_error:
                raise case.close_error
            self.closed = True

    def connect(_database):
        events.append("open")
        connection = Connection()
        connections.append(connection)
        return connection

    manager = OperatorDatabaseManager.__new__(OperatorDatabaseManager)
    manager.config = SimpleNamespace(name="test")
    manager.targets = None
    manager._log_context = lambda **kw: {}
    manager._connect = Mock(side_effect=connect)
    manager.ensure_database_and_tables = Mock(side_effect=lambda: events.append("ensure"))

    def upsert(payload, **kwargs):
        events.append(f"row:{payload['nik']}")
        if payload["nik"] == case.fail_nik:
            raise RuntimeError("sync failed midway")
        if payload["nik"] == case.skip_nik:
            raise ValueError("invalid row")
        connections[-1].pending.append(payload["nik"])

    manager.upsert_report_payload = Mock(side_effect=upsert)
    from_env = Mock(return_value=manager)
    monkeypatch.setattr(taskbot_main.OperatorDatabaseManager, "from_env", from_env)
    real_syncer = taskbot_main.DatabaseReportSyncer

    def create():
        events.append("create")
        syncer = real_syncer()
        syncer.close = Mock(wraps=syncer.close)
        instances.append(syncer)
        return syncer

    factory = Mock(side_effect=create)
    monkeypatch.setattr(taskbot_main, "DatabaseReportSyncer", factory)
    log = Mock()
    monkeypatch.setattr(taskbot_main, "logger", log)
    path = tmp_path / "items.jsonl"
    path.write_text(json.dumps({"nik": "file-row", "status": "completed"}) + "\n", encoding="utf-8")
    case.reporter = SimpleNamespace(jsonl_path=path)
    case.rows = [TransactionRow("one", "completed"), TransactionRow("two", "error")]
    case.factory, case.manager, case.from_env, case.log = factory, manager, from_env, log
    case.real_syncer = real_syncer
    return case


@pytest.mark.parametrize("mode", ["omitted", "none", "rows"])
def test_one_off_success_lifecycle(db_case, mode):
    case = db_case
    if mode == "omitted":
        result = taskbot_main._sync_report_to_database(case.reporter)
    else:
        result = taskbot_main._sync_report_to_database(
            case.reporter, None if mode == "none" else case.rows
        )
    assert result is None
    case.factory.assert_called_once_with()
    assert case.committed == (["one", "two"] if mode == "rows" else ["file-row"])
    assert case.events[:3] == ["create", "ensure", "open"]
    # Before the fix, all four assertions below observed an unclosed connection.
    case.instances[0].close.assert_called_once_with()
    case.connections[0].close.assert_called_once_with()
    assert case.connections[0].closed is True
    assert case.instances[0]._connection is None


@pytest.mark.parametrize("fail_nik", ["one", "two"])
def test_sync_error_discards_connection_even_in_legacy_wrapper(db_case, fail_nik):
    case = db_case
    case.fail_nik = fail_nik
    with pytest.raises(RuntimeError, match="sync failed midway"):
        taskbot_main._sync_report_to_database(case.reporter, case.rows)
    assert "rollback" in case.events
    assert case.committed == []
    case.connections[0].close.assert_called_once_with()
    assert case.instances[0]._connection is None
    case.instances[0].close.assert_called_once_with()


def test_partial_success_can_commit_before_strict_batch_check_raises(db_case):
    case = db_case
    case.skip_nik = "two"
    with pytest.raises(RuntimeError, match="did not persist every terminal row"):
        taskbot_main._sync_report_to_database(case.reporter, case.rows)
    assert case.committed == ["one"]
    assert case.events[-2:] == ["commit", "connection.close"]
    case.connections[0].close.assert_called_once_with()
    case.instances[0].close.assert_called_once_with()


def test_repeated_wrapper_calls_have_separate_owners_and_connections(db_case):
    case = db_case
    for _ in range(3):
        taskbot_main._sync_report_to_database(case.reporter, case.rows[:1])
    assert case.factory.call_count == len(case.connections) == 3
    assert len({id(syncer) for syncer in case.instances}) == 3
    assert len({id(connection) for connection in case.connections}) == 3
    assert case.committed == ["one"] * 3  # No wrapper-level deduplication/retry.
    for syncer, connection in zip(case.instances, case.connections):
        syncer.close.assert_called_once_with()
        connection.close.assert_called_once_with()


@pytest.mark.parametrize("mode", ["empty_list", "empty_tuple", "disabled", "missing_path"])
def test_no_resource_paths_preserve_skip_semantics(db_case, mode):
    case = db_case
    rows = [] if mode == "empty_list" else (() if mode == "empty_tuple" else None)
    reporter = SimpleNamespace() if mode == "missing_path" else case.reporter
    if mode == "disabled":
        case.from_env.side_effect = ValueError("Missing database environment variables: DB_HOST")
    assert taskbot_main._sync_report_to_database(reporter, rows) is None
    case.factory.assert_called_once_with()
    assert case.connections == []
    case.manager.ensure_database_and_tables.assert_not_called()
    case.instances[0].close.assert_called_once_with()
    if mode != "disabled":
        case.from_env.assert_not_called()


def test_constructor_itself_is_resource_free(db_case):
    syncer = db_case.real_syncer()
    assert syncer._connection is syncer._manager is None
    assert db_case.connections == []
    db_case.from_env.assert_not_called()


def test_constructor_failure_has_no_acquired_owner_to_close(db_case):
    failure = RuntimeError("constructor failed")
    db_case.factory.side_effect = failure
    with pytest.raises(RuntimeError) as caught:
        taskbot_main._sync_report_to_database(db_case.reporter)
    assert caught.value is failure
    assert db_case.instances == db_case.connections == []
    db_case.from_env.assert_not_called()


@pytest.mark.parametrize("stage", ["configuration", "setup", "open"])
def test_failure_before_connection_return_keeps_original_error(db_case, stage):
    case = db_case
    failure = ValueError("invalid database configuration")
    target = {"configuration": case.from_env,
              "setup": case.manager.ensure_database_and_tables,
              "open": case.manager._connect}[stage]
    target.side_effect = failure
    with pytest.raises(ValueError) as caught:
        taskbot_main._sync_report_to_database(case.reporter)
    assert caught.value is failure
    assert case.connections == []
    case.instances[0].close.assert_called_once_with()


def test_persistent_syncer_reuses_connection_until_explicit_close(db_case):
    case = db_case
    syncer = case.real_syncer()
    syncer(case.reporter, case.rows[:1])
    syncer(case.reporter, case.rows[1:])
    assert len(case.connections) == 1
    assert case.events.count("commit") == 2
    case.connections[0].close.assert_not_called()
    syncer.close()
    syncer.close()
    case.connections[0].close.assert_called_once_with()


@pytest.mark.parametrize("sync_error", [None, RuntimeError("primary sync"), KeyboardInterrupt("interrupt")])
@pytest.mark.parametrize("close_error", [None, OSError("secondary close"), KeyboardInterrupt("close interrupted")])
def test_wrapper_exception_precedence_and_close_attempt(monkeypatch, sync_error, close_error):
    syncer = Mock(side_effect=sync_error, return_value=None)
    syncer.close = Mock(side_effect=close_error)
    factory = Mock(return_value=syncer)
    logger = Mock()
    monkeypatch.setattr(taskbot_main, "DatabaseReportSyncer", factory)
    monkeypatch.setattr(taskbot_main, "logger", logger)
    reporter, rows = object(), [object()]
    if sync_error is not None:
        with pytest.raises(type(sync_error)) as caught:
            taskbot_main._sync_report_to_database(reporter, rows)
        assert caught.value is sync_error
    elif close_error is not None and not isinstance(close_error, Exception):
        with pytest.raises(type(close_error)) as caught:
            taskbot_main._sync_report_to_database(reporter, rows)
        assert caught.value is close_error
    else:
        assert taskbot_main._sync_report_to_database(reporter, rows) is None
    factory.assert_called_once_with()
    syncer.assert_called_once_with(reporter, rows)
    syncer.close.assert_called_once_with()
    if close_error is not None and (sync_error is not None or isinstance(close_error, Exception)):
        logger.bind.assert_called_once_with(event="report.db_sync.one_off_close_failed")
        logger.bind.return_value.exception.assert_called_once()


@pytest.mark.parametrize("sync_fails", [False, True])
def test_real_syncer_close_failure_is_logged_without_duplicate_close(db_case, sync_fails):
    case = db_case
    case.close_error = OSError("connection close unavailable")
    if sync_fails:
        failure = RuntimeError("primary sync failure")
        case.manager.upsert_report_payload.side_effect = failure
        with pytest.raises(RuntimeError) as caught:
            taskbot_main._sync_report_to_database(case.reporter, case.rows)
        assert caught.value is failure
    else:
        assert taskbot_main._sync_report_to_database(case.reporter, case.rows) is None
    case.instances[0].close.assert_called_once_with()
    case.connections[0].close.assert_called_once_with()
    assert case.connections[0].closed is False  # An attempted close is not a guarantee.
    assert case.instances[0]._connection is None
    logged_events = [call.kwargs.get("event") for call in case.log.bind.call_args_list]
    assert logged_events.count("report.db_connection.close_failed") == 1


def test_failure_after_successful_sync_still_closes_owned_connection(db_case):
    case = db_case
    failure = RuntimeError("final sync logging failed")

    def bind(**fields):
        log = Mock()
        if fields.get("event") == "report.db_sync.finished":
            log.info.side_effect = failure
        return log

    case.log.bind.side_effect = bind
    with pytest.raises(RuntimeError) as caught:
        taskbot_main._sync_report_to_database(case.reporter, case.rows)
    assert caught.value is failure
    assert case.committed == ["one", "two"]
    case.instances[0].close.assert_called_once_with()
    case.connections[0].close.assert_called_once_with()


@pytest.mark.parametrize("empty_file", [False, True])
def test_file_mode_preserves_empty_and_skipped_row_semantics(db_case, empty_file):
    case = db_case
    if empty_file:
        case.reporter.jsonl_path.write_text("", encoding="utf-8")
    else:
        case.skip_nik = "file-row"
    assert taskbot_main._sync_report_to_database(case.reporter, rows=None) is None
    assert case.committed == []
    assert len(case.connections) == 1
    assert "commit" in case.events
    case.connections[0].close.assert_called_once_with()


def test_persistent_syncer_recovers_connection_after_failed_call(db_case):
    case = db_case
    syncer = case.real_syncer()
    case.fail_nik = "one"
    with pytest.raises(RuntimeError, match="sync failed midway"):
        syncer(case.reporter, case.rows)
    case.connections[0].close.assert_called_once_with()
    case.fail_nik = None
    syncer(case.reporter, case.rows)
    assert len(case.connections) == 2
    case.connections[1].close.assert_not_called()
    syncer.close()
    case.connections[1].close.assert_called_once_with()
    assert case.committed == ["one", "two"]
