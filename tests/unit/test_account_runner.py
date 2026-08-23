from types import SimpleNamespace

from src.application.services.account_runner import AccountRunner
from src.application.use_cases.process_account import process_account, process_accounts
from src.infrastructure.browser.playwright_session import (
    BrowserSession as InfrastructureBrowserSession,
)
from src.orchestration.browser_session import (
    BrowserSession as OrchestrationBrowserSession,
)


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
