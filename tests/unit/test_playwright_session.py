from types import SimpleNamespace

import pytest

import src.infrastructure.browser.playwright_session as playwright_session_module


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
