import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from src.application.services.account_runner import AccountRunner
from src.application.use_cases.process_account import process_account, process_accounts
from src.infrastructure.browser.playwright_session import (
    BrowserSession as InfrastructureBrowserSession,
)
from src.orchestration.browser_session import (
    BrowserSession as OrchestrationBrowserSession,
)
from src.web.reporter import TransactionReporter


class FakeBoundLogger:
    def __init__(self, sink: list[tuple[str, dict, str]]) -> None:
        self.sink = sink
        self.last_bind: dict = {}

    def bind(self, **kwargs):
        self.last_bind = kwargs
        return self

    def info(self, message: str, *args, **kwargs) -> None:
        self.sink.append(("info", self.last_bind.copy(), message))

    def exception(self, message: str, *args, **kwargs) -> None:
        self.sink.append(("exception", self.last_bind.copy(), message))


class FakeReporter:
    def __init__(self, *, operator: str) -> None:
        self.operator = operator
        self.write_files_calls = 0
        self.print_summary_calls = 0

    def write_files(self) -> None:
        self.write_files_calls += 1

    def print_summary(self) -> None:
        self.print_summary_calls += 1


class BatchingFakeReporter(FakeReporter):
    def __init__(self, *, operator: str) -> None:
        super().__init__(operator=operator)
        self.rows: list[str] = []
        self._batch_size: int | None = None
        self._sync_callback = None
        self._pending_rows: list[str] = []

    def configure_batch_sync(self, sync_callback, *, batch_size: int) -> None:
        self._sync_callback = sync_callback
        self._batch_size = batch_size

    def record_terminal_rows(self, count: int) -> None:
        for _ in range(count):
            row = f"row-{len(self.rows) + 1}"
            self.rows.append(row)
            self._pending_rows.append(row)
            if len(self._pending_rows) == self._batch_size:
                self._sync_callback(tuple(self._pending_rows))
                self._pending_rows.clear()

    def flush_pending_batches(self) -> None:
        if self._pending_rows:
            self._sync_callback(tuple(self._pending_rows))
            self._pending_rows.clear()


class FakeLimiter:
    pass


class FakeSession:
    def __init__(self, config) -> None:
        self.config = config
        self.initialized = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def initialize_session(self) -> None:
        self.initialized = True

    def require_page(self):
        return "fake-page"


class ExplodingSession(FakeSession):
    def initialize_session(self) -> None:
        raise RuntimeError("boom")


class FakeProcessor:
    def __init__(self, config, page, reporter, limiter) -> None:
        self.config = config
        self.page = page
        self.reporter = reporter
        self.limiter = limiter
        self.process_calls = 0

    def process_all_niks(self) -> None:
        self.process_calls += 1


class BatchProducingProcessor(FakeProcessor):
    def process_all_niks(self) -> None:
        self.process_calls += 1
        self.reporter.record_terminal_rows(len(self.config.nik))


class PartiallyFailingProcessor(FakeProcessor):
    def process_all_niks(self) -> None:
        self.process_calls += 1
        self.reporter.record_terminal_rows(125)
        raise RuntimeError("browser session lost")


@pytest.fixture
def finalization_case():
    def build(*, mode="batch", failures=()):
        events = []
        errors = {stage: RuntimeError(f"{stage} failed") for stage in failures}

        def action(stage):
            events.append(stage)
            if stage in errors:
                raise errors[stage]

        reporter = SimpleNamespace(
            write_files=Mock(side_effect=lambda: action("write")),
            print_summary=Mock(side_effect=lambda: action("summary")),
        )
        syncer = Mock(side_effect=lambda *args: action("sync"))
        syncer.close = Mock(side_effect=lambda: action("close"))
        if mode == "batch":
            reporter.configure_batch_sync = Mock()

            def flush():
                action("flush")
                syncer(reporter, ("terminal-row",))

            reporter.flush_pending_batches = Mock(side_effect=flush)

        session = MagicMock()
        session.__enter__.return_value = session
        session.__exit__.side_effect = lambda *args: action("browser_exit") or False
        session.initialize_session.side_effect = lambda: action("initialize")
        session.require_page.return_value = "fake-page"
        processor = SimpleNamespace(
            process_all_niks=Mock(side_effect=lambda: action("process"))
        )
        log_sink = []
        logger = FakeBoundLogger(log_sink)
        logged_errors = []
        original_exception = logger.exception

        def log_exception(message):
            logged_errors.append((logger.last_bind["event"], sys.exception()))
            original_exception(message)

        logger.exception = log_exception
        runner = AccountRunner(
            reporter_factory=lambda **kwargs: reporter,
            limiter_factory=FakeLimiter,
            browser_session_factory=lambda config: session,
            transaction_processor_factory=lambda *args: processor,
            report_syncer=None if mode == "disabled" else syncer,
            logger=logger,
        )
        return SimpleNamespace(
            runner=runner,
            config=SimpleNamespace(operator_id="operator_01", nik=["3174"]),
            reporter=reporter,
            syncer=syncer,
            events=events,
            errors=errors,
            logged_errors=logged_errors,
            log_sink=log_sink,
        )

    return build


@pytest.mark.parametrize("mode", ["batch", "legacy"])
def test_write_files_failure_still_final_syncs_and_closes(finalization_case, mode):
    case = finalization_case(mode=mode, failures=("write",))

    with pytest.raises(RuntimeError) as caught:
        case.runner.run(case.config)

    assert caught.value is case.errors["write"]
    # The original implementation stopped at write, skipping both sync and close.
    assert case.events == [
        "initialize", "process", "browser_exit", "write",
        *(["flush"] if mode == "batch" else []), "sync", "close", "summary",
    ]
    assert case.syncer.call_count == 1
    case.syncer.close.assert_called_once_with()
    if mode == "batch":
        case.reporter.flush_pending_batches.assert_called_once_with()


@pytest.mark.parametrize("mode", ["batch", "legacy"])
@pytest.mark.parametrize(
    ("failures", "raised_stage"),
    [
        ((), None),
        (("sync",), None),
        (("close",), "close"),
        (("write", "sync"), "write"),
        (("sync", "close"), None),
        (("write", "sync", "close"), "write"),
        (("process",), None),
        (("process", "write", "sync", "close"), None),
        (("summary",), "summary"),
        (("write", "summary"), "write"),
        (("close", "summary"), "close"),
        (("process", "write", "sync", "close", "summary"), None),
    ],
)
def test_finalization_order_and_first_failure_contract(
    finalization_case, mode, failures, raised_stage
):
    case = finalization_case(mode=mode, failures=failures)

    if raised_stage:
        with pytest.raises(RuntimeError) as caught:
            case.runner.run(case.config)
        assert caught.value is case.errors[raised_stage]
    else:
        assert case.runner.run(case.config) == ("operator_01", not failures)

    assert case.events == [
        "initialize", "process", "browser_exit", "write",
        *(["flush"] if mode == "batch" else []), "sync", "close", "summary",
    ]
    case.reporter.write_files.assert_called_once_with()
    case.reporter.print_summary.assert_called_once_with()
    case.syncer.close.assert_called_once_with()
    if mode == "batch":
        case.reporter.flush_pending_batches.assert_called_once_with()
        case.syncer.assert_called_once_with(case.reporter, ("terminal-row",))
    else:
        case.syncer.assert_called_once_with(case.reporter)

    error_events = {
        "process": "account.run.fatal_error",
        "write": "account.report_write_error",
        "sync": "account.report_db_sync_error",
        "close": "account.report_db_close_error",
        "summary": "account.report_summary_error",
    }
    # Primary and secondary errors remain observable with their original objects.
    assert case.logged_errors == [
        (error_events[stage], case.errors[stage]) for stage in failures
    ]
    assert case.log_sink[-1][1] == {
        "event": "account.run.finished",
        "operator_id": "operator_01",
        "success": not failures,
        "status": "failed" if failures else "completed",
        "execution_status": "failed" if "process" in failures else "completed",
        "persistence_status": (
            "failed" if set(failures) & {"write", "sync", "close", "summary"} else "successful"
        ),
        "transaction_status": None,  # This legacy test double exposes no terminal rows.
    }


@pytest.mark.parametrize("failures", [("flush",), ("write", "flush", "close")])
def test_flush_failure_still_closes_once_without_legacy_sync_fallback(
    finalization_case, failures
):
    case = finalization_case(failures=failures)

    if "write" in failures:
        with pytest.raises(RuntimeError) as caught:
            case.runner.run(case.config)
        assert caught.value is case.errors["write"]
    else:
        assert case.runner.run(case.config) == ("operator_01", False)

    case.reporter.flush_pending_batches.assert_called_once_with()
    case.syncer.assert_not_called()
    case.syncer.close.assert_called_once_with()
    case.reporter.print_summary.assert_called_once_with()
    assert ("account.report_db_sync_error", case.errors["flush"]) in case.logged_errors


@pytest.mark.parametrize("failure_stage", ["initialize", "browser_exit"])
def test_account_level_failure_remains_primary_through_finalization(
    finalization_case, failure_stage
):
    case = finalization_case(failures=(failure_stage, "write", "sync", "close"))

    assert case.runner.run(case.config) == ("operator_01", False)

    assert case.logged_errors[0] == (
        "account.run.fatal_error", case.errors[failure_stage]
    )
    assert len(case.logged_errors) == 4
    case.reporter.write_files.assert_called_once_with()
    case.reporter.flush_pending_batches.assert_called_once_with()
    case.syncer.assert_called_once_with(case.reporter, ("terminal-row",))
    case.syncer.close.assert_called_once_with()


@pytest.mark.parametrize("failures", [(), ("write",), ("process", "write")])
def test_finalization_with_db_sync_disabled(finalization_case, failures):
    case = finalization_case(mode="disabled", failures=failures)

    if failures == ("write",):
        with pytest.raises(RuntimeError) as caught:
            case.runner.run(case.config)
        assert caught.value is case.errors["write"]
    else:
        assert case.runner.run(case.config) == ("operator_01", not failures)

    assert case.events == ["initialize", "process", "browser_exit", "write", "summary"]
    case.syncer.assert_not_called()
    case.syncer.close.assert_not_called()
    case.reporter.write_files.assert_called_once_with()
    case.reporter.print_summary.assert_called_once_with()


@pytest.mark.parametrize("mode", ["batch", "legacy"])
def test_finalization_supports_syncer_without_close(finalization_case, mode):
    case = finalization_case(mode=mode, failures=("write",))

    def sync_without_close(*args):
        case.syncer(*args)

    case.runner.report_syncer = sync_without_close
    with pytest.raises(RuntimeError) as caught:
        case.runner.run(case.config)

    assert caught.value is case.errors["write"]
    assert case.syncer.call_count == 1
    case.syncer.close.assert_not_called()
    case.reporter.print_summary.assert_called_once_with()


@pytest.mark.parametrize("processing_fails", [False, True])
def test_finalization_flushes_real_reporter_pending_row_after_write_failure(
    monkeypatch, tmp_path, processing_fails
):
    reporter = TransactionReporter(out_dir=str(tmp_path), operator_id="operator_01")
    events = []
    write_error = OSError("final snapshot unavailable")

    def sync(*args):
        events.append("db_attempt")
        if events.count("db_attempt") == 1:
            raise RuntimeError("DB temporarily unavailable")

    syncer = Mock(side_effect=sync)
    syncer.close = Mock(side_effect=lambda: events.append("close"))

    def process():
        reporter.complete("3174", reporter.start_item("3174"), puzzle_solved=True)
        assert reporter._pending_batch_rows == reporter.rows
        if processing_fails:
            raise RuntimeError("processing interrupted after terminal row")

    def write_files():
        events.append("write")
        raise write_error

    monkeypatch.setattr(reporter, "write_files", Mock(side_effect=write_files))
    monkeypatch.setattr(reporter, "print_summary", Mock())
    flush = Mock(wraps=reporter.flush_pending_batches)
    monkeypatch.setattr(reporter, "flush_pending_batches", flush)
    runner = AccountRunner(
        reporter_factory=lambda **kwargs: reporter,
        limiter_factory=FakeLimiter,
        browser_session_factory=FakeSession,
        transaction_processor_factory=lambda *args: SimpleNamespace(process_all_niks=process),
        report_syncer=syncer,
        logger=FakeBoundLogger([]),
    )
    config = SimpleNamespace(operator_id="operator_01", nik=["3174"])

    if processing_fails:
        assert runner.run(config) == ("operator_01", False)
    else:
        with pytest.raises(OSError) as caught:
            runner.run(config)
        assert caught.value is write_error

    assert events == ["db_attempt", "write", "db_attempt", "close"]
    flush.assert_called_once_with()
    syncer.close.assert_called_once_with()
    # One failed per-row sync and one final retry; no extra final sync or new row.
    assert len(reporter.rows) == 1
    assert reporter.rows[0].status == "completed"
    assert reporter._pending_batch_rows == []
    assert [call.args for call in syncer.call_args_list] == [
        (reporter, (reporter.rows[0],)), (reporter, (reporter.rows[0],)),
    ]
    assert len(reporter.jsonl_path.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize(
    ("statuses", "clean"),
    [
        (["completed"], True),
        (["error"], False),
        (["failed_puzzle_solve"], False),
        (["skipped_out_of_stock"], False),
        ([], False),
    ],
)
def test_account_return_remains_a_tuple_with_clean_success_semantics(finalization_case, statuses, clean):
    case = finalization_case()
    case.reporter.rows = [SimpleNamespace(nik="3174", status=status) for status in statuses]

    result = case.runner.run(case.config)

    assert type(result) is tuple
    assert result == ("operator_01", clean)
    assert case.runner.outcome["execution_status"] == "completed"
    assert case.runner.outcome["persistence_status"] == "successful"
    assert case.runner.outcome["status"] == ("completed" if clean else "completed_with_errors")
    case.reporter.flush_pending_batches.assert_called_once_with()
    case.syncer.close.assert_called_once_with()


def test_transaction_error_does_not_suppress_primary_finalization_exception(finalization_case):
    case = finalization_case(failures=("write", "sync", "close"))
    case.reporter.rows = [SimpleNamespace(nik="3174", status="error")]

    with pytest.raises(RuntimeError) as caught:
        case.runner.run(case.config)

    assert caught.value is case.errors["write"]
    assert case.runner.outcome["status"] == "failed"
    assert case.runner.outcome["transaction_status"] == "completed_with_errors"
    assert case.runner.outcome["execution_status"] == "completed"
    assert case.runner.outcome["persistence_status"] == "failed"
    case.reporter.flush_pending_batches.assert_called_once_with()
    case.syncer.close.assert_called_once_with()


def test_browser_session_shim_reexports_infrastructure_session():
    assert OrchestrationBrowserSession is InfrastructureBrowserSession


def test_account_runner_runs_single_account_and_writes_reports():
    log_sink: list[tuple[str, dict, str]] = []
    logger = FakeBoundLogger(log_sink)
    created_processors: list[FakeProcessor] = []
    created_reporters: list[FakeReporter] = []
    synced_reporters: list[FakeReporter] = []

    def reporter_factory(*, operator: str) -> FakeReporter:
        reporter = FakeReporter(operator=operator)
        created_reporters.append(reporter)
        return reporter

    def processor_factory(config, page, reporter, limiter) -> FakeProcessor:
        processor = FakeProcessor(config, page, reporter, limiter)
        created_processors.append(processor)
        return processor

    runner = AccountRunner(
        reporter_factory=reporter_factory,
        limiter_factory=FakeLimiter,
        browser_session_factory=FakeSession,
        transaction_processor_factory=processor_factory,
        report_syncer=synced_reporters.append,
        logger=logger,
    )

    result = runner.run(
        SimpleNamespace(
            operator_id="operator_01",
            email_user="tester@example.com",
            nik=["3174"],
        )
    )

    assert result == ("operator_01", True)
    assert len(created_processors) == 1
    assert created_processors[0].page == "fake-page"
    assert created_processors[0].process_calls == 1
    assert len(created_reporters) == 1
    assert created_reporters[0].write_files_calls == 1
    assert created_reporters[0].print_summary_calls == 1
    assert synced_reporters == [created_reporters[0]]
    assert [entry[0] for entry in log_sink] == ["info", "info"]
    assert log_sink[0][1]["event"] == "account.run.started"
    assert log_sink[1][1]["event"] == "account.run.finished"


def test_account_runner_logs_fatal_errors_and_returns_unsuccessful():
    log_sink: list[tuple[str, dict, str]] = []
    logger = FakeBoundLogger(log_sink)
    created_reporters: list[FakeReporter] = []

    def reporter_factory(*, operator: str) -> FakeReporter:
        reporter = FakeReporter(operator=operator)
        created_reporters.append(reporter)
        return reporter

    runner = AccountRunner(
        reporter_factory=reporter_factory,
        limiter_factory=FakeLimiter,
        browser_session_factory=ExplodingSession,
        transaction_processor_factory=FakeProcessor,
        logger=logger,
    )

    result = runner.run(
        SimpleNamespace(
            operator_id="operator_01",
            email_user="tester@example.com",
            nik=["3174"],
        )
    )

    assert result == ("operator_01", False)
    assert created_reporters[0].write_files_calls == 1
    assert created_reporters[0].print_summary_calls == 1
    assert [entry[0] for entry in log_sink] == ["info", "exception", "info"]
    assert log_sink[1][1]["event"] == "account.run.fatal_error"


def test_account_runner_logs_report_sync_failure_and_returns_unsuccessful():
    log_sink: list[tuple[str, dict, str]] = []
    logger = FakeBoundLogger(log_sink)

    def reporter_factory(*, operator: str) -> FakeReporter:
        return FakeReporter(operator=operator)

    def failing_report_syncer(reporter) -> None:
        raise RuntimeError("db unavailable")

    runner = AccountRunner(
        reporter_factory=reporter_factory,
        limiter_factory=FakeLimiter,
        browser_session_factory=FakeSession,
        transaction_processor_factory=FakeProcessor,
        report_syncer=failing_report_syncer,
        logger=logger,
    )

    result = runner.run(
        SimpleNamespace(
            operator_id="operator_01",
            email_user="tester@example.com",
            nik=["3174"],
        )
    )

    assert result == ("operator_01", False)
    assert [entry[0] for entry in log_sink] == ["info", "exception", "info"]
    assert log_sink[1][1]["event"] == "account.report_db_sync_error"


def test_account_runner_syncs_each_terminal_row_before_processing_the_next():
    log_sink: list[tuple[str, dict, str]] = []
    synced_batches: list[tuple[str, tuple[str, ...]]] = []
    logger = FakeBoundLogger(log_sink)

    def report_syncer(reporter, rows) -> None:
        synced_batches.append((reporter.operator, rows))

    runner = AccountRunner(
        reporter_factory=BatchingFakeReporter,
        limiter_factory=FakeLimiter,
        browser_session_factory=FakeSession,
        transaction_processor_factory=BatchProducingProcessor,
        report_syncer=report_syncer,
        logger=logger,
    )

    result = runner.run(
        SimpleNamespace(
            operator_id="operator_01",
            email_user="first@example.com",
            nik=[str(index) for index in range(201)],
        )
    )

    assert result == ("operator_01", True)
    assert len(synced_batches) == 201
    assert all(operator == "operator_01" for operator, _rows in synced_batches)
    assert [rows[0] for _operator, rows in synced_batches] == [
        f"row-{index}" for index in range(1, 202)
    ]


def test_account_runner_flushes_partial_batch_after_fatal_error():
    log_sink: list[tuple[str, dict, str]] = []
    synced_batches: list[tuple[str, ...]] = []
    logger = FakeBoundLogger(log_sink)

    def report_syncer(reporter, rows) -> None:
        del reporter
        synced_batches.append(rows)

    runner = AccountRunner(
        reporter_factory=BatchingFakeReporter,
        limiter_factory=FakeLimiter,
        browser_session_factory=FakeSession,
        transaction_processor_factory=PartiallyFailingProcessor,
        report_syncer=report_syncer,
        logger=logger,
    )

    result = runner.run(
        SimpleNamespace(
            operator_id="operator_01",
            email_user="first@example.com",
            nik=[str(index) for index in range(125)],
        )
    )

    assert result == ("operator_01", False)
    assert len(synced_batches) == 125
    assert all(len(rows) == 1 for rows in synced_batches)
    assert log_sink[1][1]["event"] == "account.run.fatal_error"


def test_process_account_delegates_to_account_runner():
    calls: list[object] = []

    class FakeRunner:
        def run(self, config):
            calls.append(config)
            return ("operator_01", True)

    config = SimpleNamespace(
        operator_id="operator_01", email_user="tester@example.com"
    )
    result = process_account(config, account_runner=FakeRunner())

    assert result == ("operator_01", True)
    assert calls == [config]


def test_process_accounts_runs_multiple_accounts_and_logs_thread_completion():
    log_sink: list[tuple[str, dict, str]] = []
    logger = FakeBoundLogger(log_sink)
    accounts = [
        SimpleNamespace(operator_id="operator_01", email_user="one@example.com"),
        SimpleNamespace(operator_id="operator_02", email_user="two@example.com"),
    ]

    def run_account(config):
        return config.operator_id, config.operator_id != "operator_02"

    results = process_accounts(accounts, run_account=run_account, log=logger)

    assert set(results) == {
        ("operator_01", True),
        ("operator_02", False),
    }
    assert log_sink[0][1]["event"] == "app.concurrent_start"
    thread_finish_events = [
        entry
        for entry in log_sink
        if entry[1].get("event") == "account.thread.finished"
    ]
    assert len(thread_finish_events) == 2
