from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import src.infrastructure.browser.playwright_session as playwright_session_module


@pytest.mark.parametrize("resource", ["interaction_diagnostics", "context", "browser", "playwright"])
@pytest.mark.parametrize("primary", [False, True])
@pytest.mark.parametrize("log_stage", ["bind", "debug"])
def test_cleanup_logging_does_not_mask_body_or_stop_teardown(startup_case, resource, primary, log_stage):
    case = startup_case(cleanup_failures=(resource,))
    failure = RuntimeError("body failed")
    diagnostics = Mock()
    if resource == "interaction_diagnostics":
        diagnostics.stop.side_effect = OSError("diagnostics failed")
    case.session.interaction_diagnostics = diagnostics
    if log_stage == "bind":
        case.logger.bind.side_effect = RuntimeError("logger failed")
    else:
        case.logger.bind.return_value.debug.side_effect = RuntimeError("logger failed")

    def run():
        with case.session:
            if primary:
                raise failure

    if primary:
        with pytest.raises(RuntimeError) as caught:
            run()
        assert caught.value is failure
    else:
        run()
    diagnostics.stop.assert_called_once_with(context_manager_failed=primary)
    case.context.close.assert_called_once_with()
    case.browser.close.assert_called_once_with()
    case.playwright.stop.assert_called_once_with()
    assert case.session.page is case.session.context is case.session.browser is None
    assert case.session.playwright is case.session.interaction_diagnostics is None


@pytest.mark.parametrize("fatal_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("source", ["cleanup", "logger"])
@pytest.mark.parametrize("primary", [False, True])
def test_fatal_teardown_interruptions_keep_existing_precedence(startup_case, fatal_type, source, primary):
    case = startup_case(cleanup_failures=("context",))
    interruption = fatal_type("teardown interrupted")
    if source == "cleanup":
        case.context.close.side_effect = interruption
    else:
        case.logger.bind.side_effect = interruption
    with pytest.raises(fatal_type) as caught, case.session:
        if primary:
            raise RuntimeError("body failed")
    assert caught.value is interruption
    case.context.close.assert_called_once_with()
    # Existing browser policy propagates fatal teardown immediately.
    case.browser.close.assert_not_called()


@pytest.fixture
def startup_case(monkeypatch):
    monkeypatch.setenv("TASKBOT_INTERACTION_DEBUG", "0")
    monkeypatch.setenv("TASKBOT_INTERACTION_PAUSE", "0")

    def build(*, startup_failure=None, cleanup_failures=()):
        events = []
        startup_error = ValueError(f"{startup_failure} startup failed")
        cleanup_errors = {
            resource: OSError(f"{resource} cleanup failed")
            for resource in cleanup_failures
        }

        def acquire(stage, resource):
            events.append(stage)
            if stage == startup_failure:
                raise startup_error
            return resource

        def release(resource):
            events.append(f"cleanup.{resource}")
            if resource in cleanup_errors:
                raise cleanup_errors[resource]

        page = SimpleNamespace(close=Mock())
        context = SimpleNamespace(
            new_page=Mock(side_effect=lambda: acquire("page", page)),
            close=Mock(side_effect=lambda: release("context")),
        )
        browser = SimpleNamespace(
            new_context=Mock(side_effect=lambda: acquire("context", context)),
            close=Mock(side_effect=lambda: release("browser")),
        )
        playwright = SimpleNamespace(
            firefox=SimpleNamespace(
                launch=Mock(side_effect=lambda **kwargs: acquire("launch", browser))
            ),
            stop=Mock(side_effect=lambda: release("playwright")),
        )
        starter = SimpleNamespace(start=Mock(side_effect=lambda: acquire("start", playwright)))
        monkeypatch.setattr(playwright_session_module, "sync_playwright", lambda: starter)
        logger = Mock()
        monkeypatch.setattr(playwright_session_module, "logger", logger)
        return SimpleNamespace(
            session=playwright_session_module.BrowserSession(SimpleNamespace(headless=True)),
            starter=starter,
            playwright=playwright,
            browser=browser,
            context=context,
            page=page,
            events=events,
            startup_error=startup_error,
            cleanup_errors=cleanup_errors,
            logger=logger,
        )

    return build


@pytest.mark.parametrize(
    ("failure_stage", "acquired"),
    [
        ("start", ()),
        ("launch", ("playwright",)),
        ("context", ("playwright", "browser")),
        ("page", ("playwright", "browser", "context")),
    ],
)
def test_startup_failure_releases_only_acquired_resources(
    monkeypatch, startup_case, failure_stage, acquired
):
    case = startup_case(startup_failure=failure_stage)
    exit_spy = Mock()
    monkeypatch.setattr(playwright_session_module.PlaywrightSession, "__exit__", exit_spy)

    with pytest.raises(ValueError) as caught, case.session:
        pytest.fail("startup failure must not enter the with body")

    assert caught.value is case.startup_error
    exit_spy.assert_not_called()
    stages = ["start", "launch", "context", "page"]
    assert case.events == [
        *stages[: stages.index(failure_stage) + 1],
        *(f"cleanup.{resource}" for resource in reversed(acquired)),
    ]
    # Startup owns cleanup even though the context manager never calls __exit__.
    for resource in ("playwright", "browser", "context", "page"):
        assert getattr(case.session, resource) is None
    assert case.context.close.call_count == int("context" in acquired)
    assert case.browser.close.call_count == int("browser" in acquired)
    assert case.playwright.stop.call_count == int("playwright" in acquired)
    case.page.close.assert_not_called()


@pytest.mark.parametrize("headless", [True, False])
def test_playwright_session_uses_configured_headless_mode(monkeypatch, headless: bool):
    monkeypatch.delenv("TASKBOT_INTERACTION_DEBUG", raising=False)
    monkeypatch.delenv("TASKBOT_INTERACTION_PAUSE", raising=False)
    launch_values: list[bool] = []

    class FakeBrowser:
        def new_context(self):
            return FakeContext()

        def close(self) -> None:
            return None

    class FakeContext:
        def new_page(self):
            return object()

        def close(self) -> None:
            return None

    class FakeFirefox:
        def launch(self, *, headless: bool):
            launch_values.append(headless)
            return FakeBrowser()

    class FakePlaywright:
        firefox = FakeFirefox()

        def stop(self) -> None:
            return None

    class FakePlaywrightStarter:
        def start(self):
            return FakePlaywright()

    monkeypatch.setattr(
        playwright_session_module,
        "sync_playwright",
        lambda: FakePlaywrightStarter(),
    )

    session = playwright_session_module.PlaywrightSession(
        SimpleNamespace(headless=headless)
    )
    with session:
        assert session.require_page() is not None

    assert launch_values == [headless]


@pytest.mark.parametrize(
    ("failure_stage", "cleanup_failures", "expected_cleanup"),
    [
        ("launch", ("playwright",), ["playwright"]),
        ("context", ("browser",), ["browser", "playwright"]),
        ("context", ("playwright",), ["browser", "playwright"]),
        ("context", ("browser", "playwright"), ["browser", "playwright"]),
        ("page", ("context",), ["context", "browser", "playwright"]),
        ("page", ("browser",), ["context", "browser", "playwright"]),
        ("page", ("playwright",), ["context", "browser", "playwright"]),
        (
            "page", ("context", "browser", "playwright"),
            ["context", "browser", "playwright"],
        ),
    ],
)
def test_startup_error_remains_primary_when_cleanup_fails(
    startup_case, failure_stage, cleanup_failures, expected_cleanup
):
    case = startup_case(startup_failure=failure_stage, cleanup_failures=cleanup_failures)

    with pytest.raises(ValueError) as caught:
        case.session.__enter__()

    assert caught.value is case.startup_error
    cleanup_events = [event for event in case.events if event.startswith("cleanup.")]
    assert cleanup_events == [f"cleanup.{resource}" for resource in expected_cleanup]
    assert [call.kwargs for call in case.logger.bind.call_args_list] == [
        {
            "event": "browser.session.cleanup_failed",
            "resource": resource,
            "error_type": "OSError",
        }
        for resource in cleanup_failures
    ]
    assert case.logger.bind.return_value.debug.call_count == len(cleanup_failures)

    # Explicit teardown after failed __enter__ must not repeat even failed closes.
    events_after_failure = list(case.events)
    case.session.__exit__(None, None, None)
    case.session.__exit__(None, None, None)
    assert case.events == events_after_failure
    assert case.context.close.call_count == int("context" in expected_cleanup)
    assert case.browser.close.call_count == int("browser" in expected_cleanup)
    assert case.playwright.stop.call_count == int("playwright" in expected_cleanup)
    case.page.close.assert_not_called()
    with pytest.raises(RuntimeError, match="not initialized"):
        case.session.require_page()


@pytest.mark.parametrize("body_fails", [False, True])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_normal_exit_preserves_ownership_order_and_is_idempotent(
    startup_case, body_fails, cleanup_fails
):
    resources = ("context", "browser", "playwright")
    case = startup_case(cleanup_failures=resources if cleanup_fails else ())
    workflow_error = RuntimeError("workflow failed after successful startup")

    def stop_diagnostics(**kwargs):
        case.events.append("cleanup.interaction_diagnostics")
        if cleanup_fails:
            raise OSError("diagnostics cleanup failed")

    diagnostics = SimpleNamespace(stop=Mock(side_effect=stop_diagnostics))

    def run():
        with case.session as active:
            assert active is case.session
            assert active.require_page() is case.page
            active.interaction_diagnostics = diagnostics
            if body_fails:
                raise workflow_error

    if body_fails:
        with pytest.raises(RuntimeError) as caught:
            run()
        assert caught.value is workflow_error
    else:
        run()

    assert case.events == [
        "start", "launch", "context", "page",
        "cleanup.interaction_diagnostics", "cleanup.context",
        "cleanup.browser", "cleanup.playwright",
    ]
    events_after_exit = list(case.events)
    case.session.__exit__(None, None, None)
    case.session.__exit__(None, None, None)
    assert case.events == events_after_exit
    diagnostics.stop.assert_called_once_with(context_manager_failed=body_fails)
    case.context.close.assert_called_once_with()
    case.browser.close.assert_called_once_with()
    case.playwright.stop.assert_called_once_with()
    case.page.close.assert_not_called()  # Context owns the page, as in the existing design.
    case.starter.start.assert_called_once_with()
    case.playwright.firefox.launch.assert_called_once_with(headless=True)
    case.browser.new_context.assert_called_once_with()
    case.context.new_page.assert_called_once_with()
    for resource in ("interaction_diagnostics", "page", "context", "browser", "playwright"):
        assert getattr(case.session, resource) is None
    with pytest.raises(RuntimeError, match="not initialized"):
        case.session.require_page()


def test_cleanup_before_startup_does_not_touch_unacquired_resources(startup_case):
    case = startup_case()

    case.session.__exit__(None, None, None)
    case.session.__exit__(None, None, None)

    assert case.events == []
    case.context.close.assert_not_called()
    case.browser.close.assert_not_called()
    case.playwright.stop.assert_not_called()


def test_startup_interrupt_also_releases_acquired_resources(startup_case):
    case = startup_case()
    interruption = KeyboardInterrupt("startup interrupted")
    case.browser.new_context.side_effect = interruption

    with pytest.raises(KeyboardInterrupt) as caught:
        case.session.__enter__()

    assert caught.value is interruption
    assert case.events == ["start", "launch", "cleanup.browser", "cleanup.playwright"]
    case.browser.close.assert_called_once_with()
    case.playwright.stop.assert_called_once_with()
    case.context.close.assert_not_called()


def _install_lifecycle_fakes(
    monkeypatch,
    events: list[tuple],
    *,
    trace_stop_error: bool = False,
):
    class FakePage:
        url = "https://app.test/dashboard"

        def goto(self, url: str) -> None:
            events.append(("page.goto", url))

        def wait_for_load_state(self, state: str) -> None:
            events.append(("page.load_state", state))

    class FakeTracing:
        def start(self, **kwargs) -> None:
            events.append(("trace.start", kwargs))

        def stop(self, **kwargs) -> None:
            events.append(("trace.stop", kwargs))
            if trace_stop_error:
                raise RuntimeError("trace stop failed")

    class FakeContext:
        def __init__(self) -> None:
            self.tracing = FakeTracing()
            self.page = FakePage()

        def new_page(self):
            events.append(("context.new_page",))
            return self.page

        def on(self, event: str, _callback) -> None:
            events.append(("context.on", event))

        def close(self) -> None:
            events.append(("context.close",))

    context = FakeContext()

    class FakeBrowser:
        def new_context(self):
            events.append(("browser.new_context",))
            return context

        def close(self) -> None:
            events.append(("browser.close",))

    class FakeFirefox:
        def launch(self, *, headless: bool):
            events.append(("firefox.launch", headless))
            return FakeBrowser()

    class FakePlaywright:
        firefox = FakeFirefox()

        def stop(self) -> None:
            events.append(("playwright.stop",))

    class FakePlaywrightStarter:
        def start(self):
            events.append(("playwright.start",))
            return FakePlaywright()

    class FakeLogin:
        def __init__(self, _page) -> None:
            pass

        def login(self, email: str, pin: str) -> None:
            events.append(("login", email, pin))

    class FakeDashboard:
        def __init__(self, _page) -> None:
            pass

        def get_profile_name(self) -> str:
            events.append(("dashboard.profile",))
            return "Operator"

        def assert_profile_name_is(self, expected: str) -> None:
            events.append(("dashboard.profile.assert", expected))

        def get_current_stock(self) -> str:
            events.append(("dashboard.stock",))
            return "10"

    monkeypatch.setattr(
        playwright_session_module,
        "sync_playwright",
        lambda: FakePlaywrightStarter(),
    )
    monkeypatch.setattr(playwright_session_module, "Login", FakeLogin)
    monkeypatch.setattr(playwright_session_module, "Dashboard", FakeDashboard)
    return context


def _debug_config(tmp_path, *, headless: bool = False):
    return SimpleNamespace(
        headless=headless,
        url_application="https://app.test",
        email_user="operator@example.com",
        pin_user="123456",
        operator_id="operator_07",
        run_context=SimpleNamespace(run_dir=tmp_path / "run"),
    )


@pytest.mark.parametrize("failure_stage", ["navigation", "login", "load_state", "stock"])
def test_initialize_session_failure_after_page_creation_still_cleans_up(
    monkeypatch, tmp_path, failure_stage
):
    monkeypatch.setenv("TASKBOT_INTERACTION_DEBUG", "0")
    monkeypatch.setenv("TASKBOT_INTERACTION_PAUSE", "0")
    events = []
    context = _install_lifecycle_fakes(monkeypatch, events)
    failure = RuntimeError(f"{failure_stage} setup failed")
    target, attribute = {
        "navigation": (context.page, "goto"),
        "login": (playwright_session_module.Login, "login"),
        "load_state": (context.page, "wait_for_load_state"),
        "stock": (playwright_session_module.Dashboard, "get_current_stock"),
    }[failure_stage]
    failing_setup = Mock(side_effect=failure)
    monkeypatch.setattr(target, attribute, failing_setup)
    session = playwright_session_module.BrowserSession(_debug_config(tmp_path))

    with pytest.raises(RuntimeError) as caught, session:
        assert session.require_page() is context.page
        session.initialize_session()

    assert caught.value is failure
    failing_setup.assert_called_once()
    assert events[-3:] == [("context.close",), ("browser.close",), ("playwright.stop",)]
    events_after_exit = list(events)
    session.__exit__(None, None, None)
    assert events == events_after_exit
    assert session.page is None


def test_debug_trace_starts_after_login_and_stops_before_context_on_exception(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("TASKBOT_INTERACTION_DEBUG", "1")
    monkeypatch.setenv("TASKBOT_INTERACTION_PAUSE", "0")
    events: list[tuple] = []
    _install_lifecycle_fakes(monkeypatch, events)
    session = playwright_session_module.PlaywrightSession(_debug_config(tmp_path))

    with (
        pytest.raises(RuntimeError, match="workflow failed"),
        session as active_session,
    ):
        active_session.initialize_session()
        events.append(("workflow.body",))
        raise RuntimeError("workflow failed")

    event_names = [event[0] for event in events]
    assert event_names.index("dashboard.stock") < event_names.index("trace.start")
    assert event_names.index("trace.start") < event_names.index("workflow.body")
    assert event_names.index("trace.stop") < event_names.index("context.close")
    assert event_names.index("context.close") < event_names.index("browser.close")
    assert event_names.index("browser.close") < event_names.index("playwright.stop")
    trace_start = next(event for event in events if event[0] == "trace.start")
    trace_stop = next(event for event in events if event[0] == "trace.stop")
    assert trace_start[1] == {
        "screenshots": True,
        "snapshots": True,
        "sources": True,
    }
    assert trace_stop[1] == {
        "path": str(
            tmp_path / "run" / "artifacts" / "traces" / "operator_07" / "trace.zip"
        )
    }


def test_trace_stop_failure_does_not_mask_workflow_error_or_skip_cleanup(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("TASKBOT_INTERACTION_DEBUG", "1")
    monkeypatch.setenv("TASKBOT_INTERACTION_PAUSE", "0")
    events: list[tuple] = []
    _install_lifecycle_fakes(monkeypatch, events, trace_stop_error=True)
    session = playwright_session_module.PlaywrightSession(_debug_config(tmp_path))

    with (
        pytest.raises(ValueError, match="original workflow error"),
        session as active_session,
    ):
        active_session.initialize_session()
        raise ValueError("original workflow error")

    event_names = [event[0] for event in events]
    assert "trace.stop" in event_names
    assert "context.close" in event_names
    assert "browser.close" in event_names
    assert "playwright.stop" in event_names


def test_disabled_interaction_debug_does_not_start_trace(monkeypatch, tmp_path):
    monkeypatch.setenv("TASKBOT_INTERACTION_DEBUG", "0")
    monkeypatch.setenv("TASKBOT_INTERACTION_PAUSE", "0")
    events: list[tuple] = []
    _install_lifecycle_fakes(monkeypatch, events)

    with playwright_session_module.PlaywrightSession(
        _debug_config(tmp_path)
    ) as session:
        session.initialize_session()

    assert "trace.start" not in [event[0] for event in events]
    assert not (tmp_path / "run" / "artifacts" / "traces").exists()


def test_pause_requires_debug_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("TASKBOT_INTERACTION_DEBUG", "0")
    monkeypatch.setenv("TASKBOT_INTERACTION_PAUSE", "1")

    with pytest.raises(ValueError, match="requires TASKBOT_INTERACTION_DEBUG"):
        playwright_session_module.PlaywrightSession(_debug_config(tmp_path))


def test_pause_requires_headed_browser(monkeypatch, tmp_path):
    monkeypatch.setenv("TASKBOT_INTERACTION_DEBUG", "1")
    monkeypatch.setenv("TASKBOT_INTERACTION_PAUSE", "1")

    with pytest.raises(ValueError, match="requires HEADLESS=FALSE"):
        playwright_session_module.PlaywrightSession(
            _debug_config(tmp_path, headless=True)
        )
