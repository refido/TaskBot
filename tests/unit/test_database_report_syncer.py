"""Sync adapter lifecycle and composition-root compatibility contracts."""

import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from src.web.reporter import TransactionRow


@pytest.mark.parametrize("primary", [False, True])
@pytest.mark.parametrize("log_stage", ["bind", "exception"])
def test_discard_logging_failure_keeps_sync_contract(case, primary, log_stage):
    failure = RuntimeError("batch failed")
    case.errors["close"] = OSError("close failed")
    if primary:
        case.errors["batch"] = failure

    def bind(**context):
        if context.get("event") == "report.db_connection.close_failed":
            if log_stage == "bind":
                raise RuntimeError("logger failed")
            return Mock(exception=Mock(side_effect=RuntimeError("logger failed")))
        return Mock()

    case.log.bind.side_effect = bind
    if primary:
        with pytest.raises(RuntimeError) as caught:
            case.syncer(case.reporter, case.rows)
        assert caught.value is failure
    else:
        case.syncer(case.reporter, case.rows)
        case.syncer.close()
    assert case.syncer._connection is None
    case.connections[0].close.assert_called_once_with()
    case.syncer.close()
    case.connections[0].close.assert_called_once_with()


@pytest.fixture
def case(monkeypatch):
    syncer_type = main.DatabaseReportSyncer
    module = sys.modules[syncer_type.__module__]
    case = SimpleNamespace(trace=[], connections=[], payloads=[], errors={})

    def step(name):
        case.trace.append(name)
        if name in case.errors:
            raise case.errors[name]

    class Connection:
        def __init__(self):
            self.closed = False
            self.close = Mock(side_effect=self.close_once)

        def close_once(self):
            step("close")
            self.closed = True

    def open_connection():
        step("open")
        connection = Connection()
        case.connections.append(connection)
        return connection

    def sync_payloads(payloads, *, source, connection):
        assert connection is case.connections[-1]
        case.payloads.append(list(payloads))
        step("batch")
        return SimpleNamespace(source=source, processed=1, inserted_or_updated=1, skipped=0)

    def sync_file(path, *, connection):
        assert connection is case.connections[-1]
        step("file")
        return SimpleNamespace(source=str(path), processed=0, inserted_or_updated=0, skipped=0)

    case.manager = SimpleNamespace(
        ensure_database_and_tables=Mock(side_effect=lambda: step("setup")),
        open_connection=Mock(side_effect=open_connection),
        sync_report_payloads=Mock(side_effect=sync_payloads),
        sync_report_file=Mock(side_effect=sync_file),
    )

    def from_env(**kwargs):
        assert kwargs == {"require_operator_targets": True}
        step("manager")
        return case.manager

    case.factory = Mock(side_effect=from_env)
    # This composition patch remains valid through the shared manager class.
    monkeypatch.setattr(main.OperatorDatabaseManager, "from_env", case.factory)
    case.log = Mock()
    monkeypatch.setattr(module, "logger", case.log)
    case.syncer = syncer_type()
    case.reporter = SimpleNamespace(jsonl_path=Path("fixed/items.jsonl"))
    case.rows = [TransactionRow("123", "completed", reason="ordinary reason")]
    case.module = module
    return case


def test_main_import_constructor_and_shared_setup_lock(case):
    from main import DatabaseReportSyncer

    assert type(case.syncer) is DatabaseReportSyncer
    assert vars(case.syncer) == {
        "_manager": None, "_database_ready": False,
        "_configuration_error": None, "_connection": None,
    }
    assert case.trace == []
    assert DatabaseReportSyncer._ensure_database.__globals__["_DATABASE_SETUP_LOCK"] is main._DATABASE_SETUP_LOCK
    assert DatabaseReportSyncer()._ensure_database.__globals__["_DATABASE_SETUP_LOCK"] is main._DATABASE_SETUP_LOCK


def test_lazy_reuse_file_batch_and_idempotent_close(case):
    assert case.syncer(case.reporter, case.rows) is None
    assert case.syncer(case.reporter, None) is None
    assert case.trace == ["manager", "setup", "open", "batch", "file"]
    assert case.payloads == [[main._database_report_payload(case.rows[0])]]
    case.syncer.close()
    case.syncer.close()
    assert case.trace[-1] == "close"
    case.connections[0].close.assert_called_once_with()
    assert case.syncer._connection is None


def test_close_never_opened_does_nothing(case):
    case.syncer.close()
    assert case.trace == []


@pytest.mark.parametrize("mode", ["empty_rows", "missing_report_path"])
def test_early_skip_does_not_initialize(case, mode):
    reporter = object() if mode == "missing_report_path" else case.reporter
    case.syncer(reporter, [] if mode == "empty_rows" else case.rows)
    assert case.trace == []


@pytest.mark.parametrize("message", ["Missing database environment variables: DB_HOST", "invalid config"])
def test_configuration_result_is_cached(case, message):
    case.errors["manager"] = ValueError(message)
    for _ in range(2):
        if message.startswith("Missing"):
            assert case.syncer(case.reporter, case.rows) is None
        else:
            with pytest.raises(ValueError, match="invalid config"):
                case.syncer(case.reporter, case.rows)
    assert case.trace == ["manager"]
    assert case.syncer._configuration_error == message


@pytest.mark.parametrize("stage", ["setup", "open", "batch", "file"])
def test_failure_recovery_and_setup_scope(case, stage):
    primary = RuntimeError(stage)
    case.errors[stage] = primary
    with pytest.raises(RuntimeError) as caught:
        case.syncer(case.reporter, None if stage == "file" else case.rows)
    assert caught.value is primary
    assert case.syncer._connection is None
    if stage in {"batch", "file"}:
        case.connections[0].close.assert_called_once_with()
    else:
        assert case.connections == []
    case.errors.clear()
    case.syncer(case.reporter, case.rows)
    assert case.factory.call_count == 1
    assert case.manager.ensure_database_and_tables.call_count == (2 if stage == "setup" else 1)
    case.syncer.close()


def test_closed_connection_is_replaced_without_second_close(case):
    case.syncer(case.reporter, case.rows)
    case.connections[0].closed = True
    case.syncer(case.reporter, case.rows)
    assert len(case.connections) == 2
    case.connections[0].close.assert_not_called()
    case.syncer.close()
    case.connections[1].close.assert_called_once_with()


def test_setup_ready_is_per_instance_not_global(case):
    case.syncer._ensure_database(case.manager)
    case.syncer._ensure_database(case.manager)
    other = main.DatabaseReportSyncer()
    other._ensure_database(case.manager)
    assert case.trace == ["setup", "setup"]


def test_main_syncer_factory_remains_patchable_for_composition(monkeypatch):
    sentinel = Mock()
    factory = Mock(return_value=sentinel)
    monkeypatch.setattr(main, "DatabaseReportSyncer", factory)
    runner = main._build_account_runner()
    assert runner.report_syncer is sentinel
    factory.assert_called_once_with()


@pytest.mark.parametrize("field,value", [("processed", 0), ("inserted_or_updated", 0), ("skipped", 1)])
def test_incomplete_batch_is_failure_and_discards(case, field, value):
    result = dict(source="batch", processed=1, inserted_or_updated=1, skipped=0)
    result[field] = value
    case.manager.sync_report_payloads.side_effect = None
    case.manager.sync_report_payloads.return_value = SimpleNamespace(**result)
    with pytest.raises(RuntimeError, match="did not persist every terminal row"):
        case.syncer(case.reporter, case.rows)
    case.connections[0].close.assert_called_once_with()
    assert case.syncer._connection is None


@pytest.mark.parametrize("first_import", [
    "import src.infrastructure.database.report_syncer",
    "import main",
    "from main import DatabaseReportSyncer",
    "from src.infrastructure.database.operator_store import OperatorDatabaseManager",
    "from src.web.reporter import TransactionReporter",
    "from src.application.services.account_runner import AccountRunner",
    "import src.application",
])
def test_fresh_import_identity_and_no_database_initialization(first_import):
    code = textwrap.dedent('''
        import sys
        from unittest.mock import patch
        import psycopg2
        from src.infrastructure.database.operator_store import OperatorDatabaseManager

        assert "src.infrastructure.database.report_syncer" not in sys.modules
        with patch.object(psycopg2, "connect") as connect, \
             patch.object(OperatorDatabaseManager, "from_env") as configure, \
             patch.object(OperatorDatabaseManager, "ensure_database_and_tables") as setup:
            exec(FIRST_IMPORT)
            from src.infrastructure.database import report_syncer
            import main

            assert main.DatabaseReportSyncer is report_syncer.DatabaseReportSyncer
            assert main.OperatorDatabaseManager is report_syncer.OperatorDatabaseManager
            assert main._DATABASE_SETUP_LOCK is report_syncer._DATABASE_SETUP_LOCK
            assert main._database_report_payload is report_syncer._database_report_payload
            syncer = report_syncer.DatabaseReportSyncer()
            syncer.close()
            connect.assert_not_called()
            configure.assert_not_called()
            setup.assert_not_called()
    ''').replace("FIRST_IMPORT", repr(first_import))
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
