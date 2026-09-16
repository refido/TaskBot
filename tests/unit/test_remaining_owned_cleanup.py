"""Exception identity and ownership at the four remaining cleanup boundaries."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from src.application.use_cases import export_session as usecase
from src.infrastructure.database import operator_store
from src.infrastructure.sessions import export_service as export

PRECEDENCE_CASES = [
    (None, None), (None, OSError), (ValueError, None), (ValueError, OSError),
    (None, KeyboardInterrupt), (None, SystemExit),
    (ValueError, KeyboardInterrupt), (ValueError, SystemExit),
    (KeyboardInterrupt, OSError), (SystemExit, OSError),
]


def assert_precedence(invoke, primary, cleanup):
    expected = primary if primary is not None and isinstance(cleanup, Exception) else cleanup or primary
    if expected is None:
        return invoke()
    with pytest.raises(type(expected)) as caught:
        invoke()
    assert caught.value is expected


@pytest.fixture
def database(monkeypatch):
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    connection = Mock()
    connection.cursor.return_value = cursor
    manager = operator_store.OperatorDatabaseManager.__new__(operator_store.OperatorDatabaseManager)
    manager.config = SimpleNamespace(name="audit", maintenance_name="postgres")
    manager._log_context = Mock(return_value={})
    manager._connect = Mock(return_value=connection)
    monkeypatch.setattr(operator_store, "logger", Mock())
    return SimpleNamespace(manager=manager, connection=connection, cursor=cursor)


@pytest.mark.parametrize("stage", ["select", "create"])
@pytest.mark.parametrize("primary_type,cleanup_type", PRECEDENCE_CASES)
def test_database_creation_precedence(database, stage, primary_type, cleanup_type):
    primary = primary_type("database body failed") if primary_type else None
    cleanup = cleanup_type("database close failed") if cleanup_type else None
    database.cursor.fetchone.return_value = (1,) if stage == "select" else None
    database.cursor.execute.side_effect = [primary] if stage == "select" else [None, primary]
    database.connection.close.side_effect = cleanup
    assert assert_precedence(database.manager.ensure_database_exists, primary, cleanup) is None
    database.manager._connect.assert_called_once_with("postgres")
    assert database.connection.autocommit is True
    database.connection.close.assert_called_once_with()
    assert database.cursor.execute.call_count == (1 if stage == "select" else 2)
    assert database.cursor.execute.call_args_list[0].args == (
        "SELECT 1 FROM pg_database WHERE datname = %s", ("audit",),
    )


def test_database_connect_failure_has_no_owned_connection(database):
    failure = RuntimeError("connect failed")
    database.manager._connect.side_effect = failure
    with pytest.raises(RuntimeError) as caught:
        database.manager.ensure_database_exists()
    assert caught.value is failure
    database.connection.close.assert_not_called()


@pytest.fixture
def sqlite_reader(monkeypatch, tmp_path):
    path = tmp_path / "Cookies"
    path.touch()
    connection = Mock()
    rows = [{"name": "first", "value": "one"}, {"name": "second", "value": "two"}]
    connection.execute.return_value.fetchall.return_value = rows
    connect = Mock(return_value=connection)
    monkeypatch.setattr(export.sqlite3, "connect", connect)
    return SimpleNamespace(path=path, connection=connection, connect=connect, rows=rows)


@pytest.mark.parametrize("primary_type,cleanup_type", PRECEDENCE_CASES)
def test_sqlite_read_precedence(sqlite_reader, primary_type, cleanup_type):
    case = sqlite_reader
    primary = primary_type("SQLite read failed") if primary_type else None
    cleanup = cleanup_type("SQLite close failed") if cleanup_type else None
    case.connection.execute.side_effect = primary
    case.connection.close.side_effect = cleanup
    result = assert_precedence(lambda: export.read_sqlite_cookie_rows(case.path), primary, cleanup)
    if primary is None and cleanup is None:
        assert result == case.rows
        assert result is not case.rows
        assert all(a is not b for a, b in zip(result, case.rows))
    case.connect.assert_called_once_with(case.path)
    assert case.connection.row_factory is export.sqlite3.Row
    assert "ORDER BY creation_utc ASC" in case.connection.execute.call_args.args[0]
    case.connection.close.assert_called_once_with()


def test_missing_cookie_file_acquires_nothing(sqlite_reader):
    case = sqlite_reader
    assert export.read_sqlite_cookie_rows(case.path.parent / "absent") == []
    case.connect.assert_not_called()
    case.connection.close.assert_not_called()


def test_sqlite_open_failure_acquires_nothing(sqlite_reader):
    case = sqlite_reader
    failure = RuntimeError("SQLite open failed")
    case.connect.side_effect = failure
    with pytest.raises(RuntimeError) as caught:
        export.read_sqlite_cookie_rows(case.path)
    assert caught.value is failure
    case.connection.close.assert_not_called()


@pytest.fixture
def browser_export(monkeypatch, tmp_path):
    events, errors = [], {}

    def step(name, result=None):
        events.append(name)
        if name in errors:
            raise errors[name]
        return result

    context = Mock(pages=[])
    page = Mock(url="https://example.invalid")
    page.context = context
    page.title.return_value = "Audit page"
    context.new_page.side_effect = lambda: step("page", page)
    context.close.side_effect = lambda: step("close")
    context.cookies.side_effect = lambda: step("cookies", [])
    storage = {"cookies": [], "origins": []}
    context.storage_state.return_value = storage
    context.browser.new_browser_cdp_session.return_value.send.return_value = {"cookies": []}
    playwright = Mock()
    playwright.chromium.launch_persistent_context.side_effect = lambda **kw: step("acquire", context)
    owner = MagicMock()
    owner.__enter__.return_value = playwright
    owner.__exit__.side_effect = lambda *args: step("playwright.stop", False)
    monkeypatch.setattr(export, "sync_playwright", lambda: owner)
    monkeypatch.setattr(export, "Login", Mock())
    dashboard = Mock()
    dashboard.assert_profile_name_is = Mock()
    dashboard.get_profile_name.return_value = "Audit"
    dashboard.get_current_stock.return_value = 7
    monkeypatch.setattr(export, "Dashboard", Mock(return_value=dashboard))
    tracker = Mock()
    tracker.export.return_value = []
    monkeypatch.setattr(export, "XHRTracker", Mock(return_value=tracker))
    web_storage = {"localStorage": {"theme": "dark"}, "sessionStorage": {}}
    monkeypatch.setattr(export, "capture_browser_state", Mock(return_value=web_storage))
    reader = Mock(side_effect=lambda path: step("sqlite.read", []))
    monkeypatch.setattr(export, "read_sqlite_cookie_rows", reader)
    writer = Mock(side_effect=lambda *args: step("write"))
    monkeypatch.setattr(export, "write_json", writer)
    monkeypatch.setattr(export, "log_print", Mock())
    monkeypatch.setattr(export, "logger", Mock())
    monkeypatch.setattr(export, "datetime", Mock(now=Mock(return_value=datetime(2026, 9, 15, tzinfo=UTC))))
    config = SimpleNamespace(
        operator_id="operator_audit", headless=True, url_application=page.url,
        email_user="audit@example.invalid", pin_user="000000",
    )
    return SimpleNamespace(
        run=lambda: export.export_account_session(config, tmp_path),
        context=context, page=page, playwright=playwright, owner=owner, reader=reader,
        writer=writer, events=events, errors=errors, root=tmp_path,
        storage=storage, web_storage=web_storage,
    )


@pytest.mark.parametrize("stage", ["page", "cookies"])
@pytest.mark.parametrize("primary_type,cleanup_type", PRECEDENCE_CASES)
def test_browser_export_precedence(browser_export, stage, primary_type, cleanup_type):
    case = browser_export
    primary = primary_type("export body failed") if primary_type else None
    cleanup = cleanup_type("context close failed") if cleanup_type else None
    if primary:
        case.errors[stage] = primary
    if cleanup:
        case.errors["close"] = cleanup
    result = assert_precedence(case.run, primary, cleanup)
    case.context.close.assert_called_once_with()
    case.owner.__exit__.assert_called_once()
    assert case.events.index("close") < case.events.index("playwright.stop")
    if primary is None and cleanup is None:
        artifact_dir = case.root / "operator-audit"
        assert result == export.SessionArtifacts("operator_audit", artifact_dir, artifact_dir / "profile", 0, 0)
        assert case.events.index("playwright.stop") < case.events.index("sqlite.read") < case.events.index("write")
        payloads = {call.args[0].name: call.args[1] for call in case.writer.call_args_list}
        assert list(payloads) == [
            "cookies_playwright.json", "cookies_cdp.json", "cookies_sqlite.json",
            "cookies_enriched.json", "storage_state.json", "web_storage.json",
            "network_xhr.json", "session_summary.json",
        ]
        assert payloads["cookies_playwright.json"] == payloads["cookies_sqlite.json"] == []
        assert payloads["cookies_cdp.json"] == {"cookies": []}
        assert payloads["storage_state.json"] == case.storage
        assert payloads["web_storage.json"] == case.web_storage
        assert payloads["session_summary.json"]["captured_at_iso"] == "2026-09-15T00:00:00+00:00"
        assert payloads["session_summary.json"]["current_stock"] == 7
        case.page.wait_for_timeout.assert_any_call(export.DEFAULT_NETWORK_WAIT_MS)
    else:
        case.reader.assert_not_called()
        case.writer.assert_not_called()


def test_context_acquisition_failure_has_nothing_to_close(browser_export):
    failure = RuntimeError("context launch failed")
    browser_export.errors["acquire"] = failure
    with pytest.raises(RuntimeError) as caught:
        browser_export.run()
    assert caught.value is failure
    browser_export.context.close.assert_not_called()
    browser_export.owner.__exit__.assert_called_once()


def test_export_uses_existing_page_without_creating_another(browser_export):
    browser_export.context.pages = [browser_export.page]
    browser_export.run()
    browser_export.context.new_page.assert_not_called()
    browser_export.context.close.assert_called_once_with()


@pytest.fixture
def export_usecase(monkeypatch, tmp_path):
    errors, events, failed_operators = {}, [], []
    log = Mock()
    log.bind.side_effect = lambda **kw: events.append(kw["event"]) or log

    def complete():
        events.append("complete")
        if "cleanup" in errors:
            raise errors["cleanup"]

    def run_exports(*args, **kwargs):
        events.append("export")
        if "primary" in errors:
            raise errors["primary"]
        return [], failed_operators, tmp_path

    log.complete.side_effect = complete
    exporter = Mock(side_effect=run_exports)
    monkeypatch.setattr(usecase, "export_configured_sessions", exporter)
    kwargs = dict(
        config_factory=lambda: SimpleNamespace(),
        configure_logging_func=lambda **kw: {"run_id": "audit", "json_log_path": "not-written"},
        log=log,
    )
    return SimpleNamespace(
        run=lambda: usecase.run_user_session_export(**kwargs), kwargs=kwargs,
        log=log, errors=errors, events=events, exporter=exporter, failed_operators=failed_operators,
    )


@pytest.mark.parametrize("primary_type,cleanup_type", PRECEDENCE_CASES)
def test_export_usecase_completion_precedence(export_usecase, primary_type, cleanup_type):
    case = export_usecase
    primary = primary_type("export usecase failed") if primary_type else None
    cleanup = cleanup_type("log completion failed") if cleanup_type else None
    if primary:
        case.errors["primary"] = primary
    if cleanup:
        case.errors["cleanup"] = cleanup
    result = assert_precedence(case.run, primary, cleanup)
    if primary is None and cleanup is None:
        assert result == 0
    assert case.events == ["user_sessions.start", "export"] + (
        [] if primary else ["user_sessions.finished"]
    ) + ["complete"]
    case.log.complete.assert_called_once_with()


@pytest.mark.parametrize("missing", [False, True])
def test_export_completion_remains_optional(export_usecase, missing):
    if missing:
        del export_usecase.log.complete
    else:
        export_usecase.log.complete = None
    assert export_usecase.run() == 0
    assert "complete" not in export_usecase.events


def test_configuration_failure_does_not_enter_export_finalization(export_usecase):
    failure = RuntimeError("configuration failed")
    export_usecase.kwargs["config_factory"] = Mock(side_effect=failure)
    with pytest.raises(RuntimeError) as caught:
        export_usecase.run()
    assert caught.value is failure
    export_usecase.log.complete.assert_not_called()
    export_usecase.exporter.assert_not_called()


def test_failed_operator_result_still_completes_logging(export_usecase):
    export_usecase.failed_operators.append("operator_audit")
    assert export_usecase.run() == 1
    export_usecase.log.complete.assert_called_once_with()
