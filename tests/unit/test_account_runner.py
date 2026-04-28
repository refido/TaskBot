from types import SimpleNamespace

from src.application.services.account_runner import AccountRunner
from src.application.use_cases.process_account import process_account, process_accounts
from src.infrastructure.browser.playwright_session import BrowserSession as InfrastructureBrowserSession
from src.orchestration.browser_session import BrowserSession as OrchestrationBrowserSession


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


def test_browser_session_shim_reexports_infrastructure_session():
    assert OrchestrationBrowserSession is InfrastructureBrowserSession


def test_account_runner_runs_single_account_and_writes_reports():
    log_sink: list[tuple[str, dict, str]] = []
    logger = FakeBoundLogger(log_sink)
    created_processors: list[FakeProcessor] = []
    created_reporters: list[FakeReporter] = []

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
        logger=logger,
    )

    result = runner.run(SimpleNamespace(email_user="tester@example.com", nik=["3174"]))

    assert result == ("tester@example.com", True)
    assert len(created_processors) == 1
    assert created_processors[0].page == "fake-page"
    assert created_processors[0].process_calls == 1
    assert len(created_reporters) == 1
    assert created_reporters[0].write_files_calls == 1
    assert created_reporters[0].print_summary_calls == 1
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

    result = runner.run(SimpleNamespace(email_user="tester@example.com", nik=["3174"]))

    assert result == ("tester@example.com", False)
    assert created_reporters[0].write_files_calls == 1
    assert created_reporters[0].print_summary_calls == 1
    assert [entry[0] for entry in log_sink] == ["info", "exception", "info"]
    assert log_sink[1][1]["event"] == "account.run.fatal_error"


def test_process_account_delegates_to_account_runner():
    calls: list[object] = []

    class FakeRunner:
        def run(self, config):
            calls.append(config)
            return ("tester@example.com", True)

    config = SimpleNamespace(email_user="tester@example.com")
    result = process_account(config, account_runner=FakeRunner())

    assert result == ("tester@example.com", True)
    assert calls == [config]


def test_process_accounts_runs_multiple_accounts_and_logs_thread_completion():
    log_sink: list[tuple[str, dict, str]] = []
    logger = FakeBoundLogger(log_sink)
    accounts = [
        SimpleNamespace(email_user="one@example.com"),
        SimpleNamespace(email_user="two@example.com"),
    ]

    def run_account(config):
        return config.email_user, config.email_user != "two@example.com"

    results = process_accounts(accounts, run_account=run_account, log=logger)

    assert set(results) == {
        ("one@example.com", True),
        ("two@example.com", False),
    }
    assert log_sink[0][1]["event"] == "app.concurrent_start"
    thread_finish_events = [
        entry for entry in log_sink if entry[1].get("event") == "account.thread.finished"
    ]
    assert len(thread_finish_events) == 2
